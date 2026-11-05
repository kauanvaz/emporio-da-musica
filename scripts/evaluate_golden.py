import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.agent import create_store_agent, run_store_agent
from backend.config import Settings as BackendSettings
from backend.schemas import ChatMessage
from mcp_server.domain.models import normalize_search_text

logger = logging.getLogger(__name__)

DATASET_PATH = Path("evaluation/golden_dataset.jsonl")
REPORT_PATH = Path("evaluation/golden_report.json")

_STORE_TOOL_NAMES = {
    "search_products",
    "list_active_promotions",
    "get_order_status",
    "query_policy",
}

_DETERMINISTIC_CHECKS = (
    "expected_tools",
    "forbidden_tools",
    "arguments",
    "status",
)
_LLM_CHECKS = ("required_facts", "groundedness")

AnswerStatus = Literal[
    "answered",
    "partially_answered",
    "not_answerable",
    "out_of_scope",
]


class GoldenSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(min_length=1)
    ragas_evaluator_model: str = Field(min_length=1)


class GoldenCase(BaseModel):
    id: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    question: str = Field(min_length=1)
    expected_tools: list[str] = Field(min_length=1)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expected_status: AnswerStatus
    required_facts: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_tool_expectations(self) -> "GoldenCase":
        expected = set(self.expected_tools)
        forbidden = set(self.forbidden_tools)
        if expected & forbidden:
            raise ValueError("expected_tools and forbidden_tools must not overlap")
        unknown_expected = expected - _STORE_TOOL_NAMES
        unknown_forbidden = forbidden - _STORE_TOOL_NAMES
        if unknown_expected or unknown_forbidden:
            raise ValueError("dataset contains an unknown store tool name")
        if not set(self.expected_args) <= expected:
            raise ValueError("expected_args keys must be present in expected_tools")
        return self


class _FactVerdict(BaseModel):
    index: int
    present: bool


class _FactEvaluation(BaseModel):
    verdicts: list[_FactVerdict]


class _GroundednessEvaluation(BaseModel):
    grounded: bool


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: str
    is_error: bool


def load_dataset(path: Path) -> list[GoldenCase]:
    lines = path.read_text(encoding="utf-8").splitlines()
    cases: list[GoldenCase] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            cases.append(GoldenCase.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: invalid case: {exc}") from exc
    if not cases:
        raise ValueError(f"{path} is empty.")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError(f"{path} has duplicate ids.")
    return cases


def extract_tool_calls(messages: Sequence[BaseMessage]) -> list[ToolCallRecord]:
    results: dict[str, tuple[str, bool]] = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        results[message.tool_call_id] = (
            _tool_result_text(message),
            message.status == "error",
        )

    calls: list[ToolCallRecord] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls:
            name = str(tool_call["name"])
            if name not in _STORE_TOOL_NAMES:
                continue
            result, is_error = results.get(str(tool_call["id"]), ("", False))
            calls.append(
                ToolCallRecord(
                    name=name,
                    arguments=dict(tool_call["args"]),
                    result=result,
                    is_error=is_error,
                )
            )
    return calls


def _tool_result_text(message: ToolMessage) -> str:
    parts: list[str] = []
    if isinstance(message.content, str):
        parts.append(message.content)
    elif message.content:
        parts.append(json.dumps(message.content, ensure_ascii=False, default=str))
    if isinstance(message.artifact, dict):
        structured = message.artifact.get("structured_content")
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    return "\n".join(dict.fromkeys(parts))


def arguments_match(
    calls: Sequence[ToolCallRecord],
    expected_args: dict[str, dict[str, Any]],
) -> bool:
    for tool_name, expected in expected_args.items():
        if not any(
            call.name == tool_name and _matches(call.arguments, expected)
            for call in calls
        ):
            return False
    return True


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _matches(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _matches(actual_item, expected_item)
                for actual_item, expected_item in zip(actual, expected, strict=True)
            )
        )
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, int | float | Decimal):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError):
            return False
    if isinstance(expected, str):
        return isinstance(actual, str) and normalize_search_text(
            actual
        ) == normalize_search_text(expected)
    if expected is None:
        return actual is None
    return actual == expected


async def _complete_json(
    client: AsyncOpenAI,
    model: str,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, default=str),
            },
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The evaluator model returned an empty response.")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The evaluator model returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise TypeError("The evaluator model did not return a JSON object.")
    return payload


def _normalized_fact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("verdicts")
    if raw is None:
        raw = payload.get("facts")
    if raw is None:
        raw = payload

    if isinstance(raw, dict):
        verdicts: list[dict[str, Any]] = []
        for position, (key, value) in enumerate(raw.items(), 1):
            index = int(key) if str(key).isdigit() else position
            if isinstance(value, bool):
                verdicts.append({"index": index, "present": value})
            elif isinstance(value, dict):
                verdict = dict(value)
                verdict.setdefault("index", index)
                verdicts.append(verdict)
        return {"verdicts": verdicts}

    if isinstance(raw, list):
        verdicts = []
        for position, value in enumerate(raw, 1):
            if isinstance(value, bool):
                verdicts.append({"index": position, "present": value})
            elif isinstance(value, dict):
                verdict = dict(value)
                verdict.setdefault("index", position)
                verdicts.append(verdict)
        return {"verdicts": verdicts}

    return payload


async def judge_required_facts(
    client: AsyncOpenAI,
    model: str,
    *,
    question: str,
    answer: str,
    facts: Sequence[str],
) -> list[bool]:
    if not facts:
        return []
    payload = await _complete_json(
        client,
        model,
        system_prompt=(
            "You are a strict fact-checking evaluator. Determine whether each "
            "required fact is clearly present in the assistant's final answer. "
            "A fact is present when the answer communicates the same information, "
            "even with different wording or formatting. If a required fact has "
            "multiple parts, all parts must be present. Do not infer information "
            "that the answer does not state. Return a JSON object with exactly one "
            'key, "verdicts", containing one object per required fact with the '
            'integer field "index" and the boolean field "present".'
        ),
        user_payload={
            "question": question,
            "answer": answer,
            "required_facts": [
                {"index": position, "fact": fact}
                for position, fact in enumerate(facts, 1)
            ],
        },
    )
    try:
        evaluation = _FactEvaluation.model_validate(_normalized_fact_payload(payload))
    except ValidationError as exc:
        raise RuntimeError("The evaluator returned invalid fact verdicts.") from exc

    verdicts = {verdict.index: verdict.present for verdict in evaluation.verdicts}
    expected_indices = set(range(1, len(facts) + 1))
    if set(verdicts) != expected_indices or len(evaluation.verdicts) != len(facts):
        raise RuntimeError("The evaluator did not return one verdict per fact.")
    return [verdicts[index] for index in range(1, len(facts) + 1)]


async def judge_groundedness(
    client: AsyncOpenAI,
    model: str,
    *,
    question: str,
    answer: str,
    calls: Sequence[ToolCallRecord],
) -> bool:
    payload = await _complete_json(
        client,
        model,
        system_prompt=(
            "You are a strict groundedness evaluator for a store assistant. The "
            "assistant may only state operational facts that are supported by the "
            "tool call arguments and results. Operational facts include prices, "
            "stock quantities, availability, order statuses, dates, payment "
            "methods, tracking codes, discounts, promotional prices, product names, "
            "totals, categories and order items. The answer is grounded when every "
            "operational value it states is present in or directly computable from "
            "the provided tool results. Values repeated from the user's question or "
            "from tool arguments are allowed. Greetings, suggestions and general "
            "wording do not require support. Return a JSON object with exactly one "
            'boolean key, "grounded".'
        ),
        user_payload={
            "question": question,
            "answer": answer,
            "tool_calls": [
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "is_error": call.is_error,
                    "result": call.result,
                }
                for call in calls
            ],
        },
    )
    try:
        return _GroundednessEvaluation.model_validate(payload).grounded
    except ValidationError as exc:
        raise RuntimeError(
            "The evaluator returned an invalid groundedness verdict."
        ) from exc


async def evaluate_case(
    case: GoldenCase,
    *,
    agent: Any,
    backend_settings: BackendSettings,
    evaluator_client: AsyncOpenAI,
    evaluator_model: str,
) -> dict[str, bool]:
    run = await run_store_agent(
        agent,
        message=case.question,
        history=case.history,
        max_history_messages=backend_settings.max_history_messages,
    )
    calls = extract_tool_calls(run.messages)
    called_names = [call.name for call in calls]

    logger.info(
        "Case %s: tools=%s status=%s answer=%s",
        case.id,
        [{"name": call.name, "arguments": call.arguments} for call in calls],
        run.answer.status,
        run.answer.answer,
    )

    facts_verdicts, grounded = await asyncio.gather(
        judge_required_facts(
            evaluator_client,
            evaluator_model,
            question=case.question,
            answer=run.answer.answer,
            facts=case.required_facts,
        ),
        judge_groundedness(
            evaluator_client,
            evaluator_model,
            question=case.question,
            answer=run.answer.answer,
            calls=calls,
        ),
    )

    results = {
        "expected_tools": all(name in called_names for name in case.expected_tools),
        "forbidden_tools": not any(
            name in called_names for name in case.forbidden_tools
        ),
        "arguments": arguments_match(calls, case.expected_args),
        "status": run.answer.status == case.expected_status,
        "required_facts": all(facts_verdicts),
        "groundedness": grounded,
    }
    results["passed"] = all(results.values())
    logger.info(
        "Case %s checks=%s facts=%s",
        case.id,
        {key: value for key, value in results.items() if key != "passed"},
        facts_verdicts,
    )
    return results


async def run_evaluation() -> dict[str, Any]:
    golden_settings = GoldenSettings()
    backend_settings = BackendSettings()
    cases = load_dataset(DATASET_PATH)
    evaluator_client = AsyncOpenAI(api_key=golden_settings.openai_api_key)

    tools = await MCPAdapter(backend_settings.mcp_server_url).list_tools()
    agent = create_store_agent(settings=backend_settings, tools=tools)

    results: dict[str, dict[str, bool]] = {}
    for position, case in enumerate(cases, 1):
        logger.info("Evaluating %d/%d: %s", position, len(cases), case.id)
        results[case.id] = await evaluate_case(
            case,
            agent=agent,
            backend_settings=backend_settings,
            evaluator_client=evaluator_client,
            evaluator_model=golden_settings.ragas_evaluator_model,
        )

    checks = (*_DETERMINISTIC_CHECKS, *_LLM_CHECKS, "passed")
    aggregate = {
        check: round(sum(case[check] for case in results.values()) / len(results), 4)
        for check in checks
    }
    return {"aggregate": aggregate, "cases": results}


def main() -> None:
    load_dotenv(".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = asyncio.run(run_evaluation())
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Report written to %s", REPORT_PATH)


if __name__ == "__main__":
    main()
