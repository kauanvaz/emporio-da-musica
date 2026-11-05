import asyncio
import json
import logging
import statistics
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.mcp import MCPAdapter
from langchain_core.messages import BaseMessage, ToolMessage
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from ragas.embeddings.base import embedding_factory
from ragas.llms.base import llm_factory
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecisionWithReference,
    ContextRecall,
    Faithfulness,
)

from backend.agent import create_store_agent, run_store_agent
from backend.config import Settings as BackendSettings
from mcp_server.config import Settings as MCPSettings
from mcp_server.domain.models import PolicyQueryResult
from mcp_server.server import build_dependencies, build_server

logger = logging.getLogger(__name__)

DATASET_PATH = Path("evaluation/ragas_dataset.jsonl")
REPORT_PATH = Path("evaluation/ragas_report.json")


class RagasSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(min_length=1)
    ragas_evaluator_model: str = Field(min_length=1)
    ragas_embedding_model: str = Field(min_length=1)


class EvaluationQuestion(BaseModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reference: str = Field(min_length=1)


def load_dataset(path: Path) -> list[EvaluationQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    questions: list[EvaluationQuestion] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            questions.append(EvaluationQuestion.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid question: {exc}") from exc
    if not questions:
        raise ValueError(f"{path} is empty.")
    if len({question.id for question in questions}) != len(questions):
        raise ValueError(f"{path} has duplicate ids.")
    return questions


def build_metrics(settings: RagasSettings) -> dict[str, Any]:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    llm = llm_factory(settings.ragas_evaluator_model, client=client)
    # Modelos com reasoning rejeitam `max_tokens` e `top_p` e só aceitam a
    # temperatura padrão; os defaults do Ragas são ajustados para isso.
    llm.model_args.pop("max_tokens", None)
    llm.model_args.pop("top_p", None)
    llm.model_args["max_completion_tokens"] = 4096
    llm.model_args["temperature"] = 1.0
    embeddings = embedding_factory(
        "openai", model=settings.ragas_embedding_model, client=client
    )
    return {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
        "context_recall": ContextRecall(llm=llm),
        "context_precision": ContextPrecisionWithReference(llm=llm),
    }


def retrieved_contexts(messages: list[BaseMessage]) -> list[str]:
    """Textos dos chunks que o próprio agente recebeu de `query_policy` no turno."""
    contexts: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name != "query_policy":
            continue
        if message.status != "success" or not isinstance(message.artifact, dict):
            continue
        result = PolicyQueryResult.model_validate(
            message.artifact["structured_content"]
        )
        contexts.extend(chunk.text for chunk in result.chunks)
    return contexts


async def score_question(
    item: EvaluationQuestion,
    agent: Any,
    metrics: dict[str, Any],
    max_history_messages: int,
) -> dict[str, float]:
    run = await run_store_agent(
        agent,
        message=item.question,
        history=[],
        max_history_messages=max_history_messages,
    )
    contexts = retrieved_contexts(run.messages)
    if not contexts:
        raise RuntimeError(f"{item.id}: the agent did not call query_policy.")

    response = run.answer.answer
    results = await asyncio.gather(
        metrics["faithfulness"].ascore(
            user_input=item.question,
            response=response,
            retrieved_contexts=contexts,
        ),
        metrics["answer_relevancy"].ascore(
            user_input=item.question,
            response=response,
        ),
        metrics["context_recall"].ascore(
            user_input=item.question,
            retrieved_contexts=contexts,
            reference=item.reference,
        ),
        metrics["context_precision"].ascore(
            user_input=item.question,
            reference=item.reference,
            retrieved_contexts=contexts,
        ),
    )
    return {
        name: round(float(result.value), 4)
        for name, result in zip(metrics, results, strict=True)
    }


async def run_evaluation() -> dict[str, Any]:
    ragas_settings = RagasSettings()
    backend_settings = BackendSettings()
    questions = load_dataset(DATASET_PATH)
    metrics = build_metrics(ragas_settings)

    server = build_server(build_dependencies(MCPSettings()))
    tools = await MCPAdapter(server).list_tools()
    agent = create_store_agent(settings=backend_settings, tools=tools)

    scores: dict[str, dict[str, float]] = {}
    for position, item in enumerate(questions, 1):
        logger.info("Evaluating %d/%d: %s", position, len(questions), item.id)
        scores[item.id] = await score_question(
            item, agent, metrics, backend_settings.max_history_messages
        )

    aggregate = {
        name: round(statistics.fmean(question[name] for question in scores.values()), 4)
        for name in metrics
    }
    aggregate["ragas_score"] = round(
        statistics.harmonic_mean([aggregate[name] for name in metrics]), 4
    )
    return {"aggregate": aggregate, "questions": scores}


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
