from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr, ValidationError

from backend.config import Settings
from backend.prompts.builder import StoreProfile, build_system_prompt
from backend.schemas import AgentAnswer, ChatMessage

_STORE_PROFILE = StoreProfile(
    name="Empório da Música",
    location="Campo Grande/MS",
    persona=(
        "Você faz parte da equipe de atendimento da loja e conversa com clientes "
        "por mensagens de texto. Seja acolhedor, informal e profissional, use "
        "português do Brasil e trate cada pessoa com atenção e respeito."
    ),
    scope=(
        "Atenda somente assuntos relacionados à Empório da Música: produtos, "
        "preços, estoque, disponibilidade, promoções, pedidos e políticas da "
        "loja. Assuntos alheios a esse escopo não fazem parte do atendimento."
    ),
)

_CAPABILITY_RULES = [
    (
        "Use `search_products` para buscar produtos por termo, categoria, faixa "
        "de preço, disponibilidade e ordenação. Para categorias conhecidas "
        "(Violões, Ukuleles, Guitarras, Baixos, Baterias e Percussão, Teclados e "
        "Pianos), informe a categoria em `category` e o tipo específico em "
        "`query`. Use termos no singular em `query` (violão, ukulele, guitarra) "
        "e não repita em `query` a categoria já informada. Não repita a mesma "
        "busca nem percorra páginas adicionais: informe a quantidade total de "
        "resultados e, quando `has_more` for verdadeiro, diga que existem mais "
        "opções além das exibidas."
    ),
    (
        "Use `list_active_promotions` para consultar promoções ativas. Para "
        "filtrar por categoria, informe-a em `category`; use `query` para nome "
        "de produto ou descrição. A tool já retorna preço original, percentual, "
        "preço promocional e disponibilidade; não aplique descontos adicionais "
        "por conta própria. Não consulte promoções quando o cliente pedir "
        "apenas produtos, preços, estoque ou ordenação."
    ),
    (
        "Use `get_order_status` quando a mensagem informar um número de pedido "
        "ou se referir a um pedido mencionado no histórico. Ao responder, "
        "informe o status, o valor total e a forma de pagamento, além dos itens "
        "quando relevante. A tool já retorna status, itens, pagamento, total, "
        "rastreamento e previsão de entrega; não consulte `query_policy` para "
        "responder sobre esses dados operacionais e não antecipe regras que o "
        "cliente não perguntou."
    ),
    (
        "Use `query_policy` para horário, endereço e contato, pagamentos, "
        "parcelamento, frete e entrega, promoções e cumulatividade, trocas e "
        "devoluções, garantia, privacidade e procedimentos de atendimento."
    ),
    (
        "Combine mais de uma tool no mesmo turno somente quando a pergunta "
        "envolver dados operacionais e políticas da loja. Responda assim que "
        "tiver os dados necessários; não faça chamadas de confirmação, não "
        "repita tools e não percorra todas as páginas de uma busca."
    ),
]

_OUTPUT_CONTRACT = """Retorne um objeto `AgentAnswer` com exatamente estes campos:
- `status`: um de `answered`, `partially_answered`, `not_answerable` ou `out_of_scope`;
- `answer`: o texto em português do Brasil que será exibido ao cliente;
- `requires_human_support`: `true` somente quando a solicitação exigir uma decisão ou operação que você não pode executar;
- `human_support_reason`: motivo curto quando `requires_human_support` for `true`; caso contrário, `null`.
"""


class AgentExecutionError(RuntimeError):
    pass


def create_store_agent(
    *,
    settings: Settings,
    tools: Sequence[BaseTool],
    model: BaseChatModel | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    api_key = SecretStr(settings.openai_api_key) if settings.openai_api_key else None
    chat_model = model or ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=api_key,
    )
    system_prompt = build_system_prompt(
        store_profile=_STORE_PROFILE,
        capability_rules=_CAPABILITY_RULES,
        output_contract=_OUTPUT_CONTRACT,
    )
    return create_agent(
        model=chat_model,
        tools=list(tools),
        system_prompt=system_prompt,
        response_format=ToolStrategy(schema=AgentAnswer, handle_errors=False),
        name="emporio-agent",
    )


def select_history_window(
    history: Sequence[ChatMessage],
    max_history_messages: int,
) -> list[ChatMessage]:
    if max_history_messages < 1:
        raise ValueError("max_history_messages must be greater than zero.")
    return list(history[-max_history_messages:])


def build_agent_input(
    *,
    message: str,
    history: Sequence[ChatMessage],
    max_history_messages: int,
) -> dict[str, list[BaseMessage]]:
    messages: list[BaseMessage] = []
    for item in select_history_window(history, max_history_messages):
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        else:
            messages.append(AIMessage(content=item.content))
    messages.append(HumanMessage(content=message))
    return {"messages": messages}


def extract_agent_answer(result: Mapping[str, Any]) -> AgentAnswer:
    structured_response = result.get("structured_response")
    if structured_response is None:
        raise AgentExecutionError(
            "Agent finished without a structured AgentAnswer response."
        )
    if isinstance(structured_response, AgentAnswer):
        return structured_response
    try:
        return AgentAnswer.model_validate(structured_response)
    except ValidationError as exc:
        raise AgentExecutionError(
            "Agent returned a structured response outside the AgentAnswer schema."
        ) from exc


@dataclass(frozen=True)
class AgentRun:
    """Resposta final do agente e mensagens produzidas no turno."""

    answer: AgentAnswer
    messages: list[BaseMessage]


async def run_store_agent(
    agent: CompiledStateGraph[Any, Any, Any, Any],
    *,
    message: str,
    history: Sequence[ChatMessage],
    max_history_messages: int,
) -> AgentRun:
    agent_input = build_agent_input(
        message=message,
        history=history,
        max_history_messages=max_history_messages,
    )
    result = await agent.ainvoke(agent_input)
    # Mantém somente as mensagens geradas neste turno, sem o histórico enviado.
    turn_messages = list(result.get("messages", []))[len(agent_input["messages"]) :]
    return AgentRun(answer=extract_agent_answer(result), messages=turn_messages)


__all__ = [
    "AgentExecutionError",
    "AgentRun",
    "build_agent_input",
    "create_store_agent",
    "extract_agent_answer",
    "run_store_agent",
    "select_history_window",
]
