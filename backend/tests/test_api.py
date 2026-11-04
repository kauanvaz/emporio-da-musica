from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from backend.schemas import AgentAnswer, ChatMessage

_GENERIC_ERROR_MESSAGE = (
    "Não foi possível processar sua mensagem agora. Tente novamente em instantes."
)


def test_chat_with_valid_message_returns_answer(
    fake_api: Any,
    answer_message: Callable[..., AIMessage],
) -> None:
    with fake_api([answer_message()]) as api:
        response = api.client.post(
            "/chat",
            json={
                "session_id": "session-1",
                "message": "Quais violões vocês têm?",
            },
        )

    assert response.status_code == 200
    body = response.json()
    answer = AgentAnswer.model_validate(body["answer"])
    assert answer.status == "answered"
    assert answer.answer == "Temos violões a partir de R$ 899,10."
    assert answer.requires_human_support is False
    assert answer.human_support_reason is None


def test_chat_with_empty_message_returns_422(fake_api: Any) -> None:
    with fake_api([]) as api:
        response = api.client.post(
            "/chat",
            json={"session_id": "session-1", "message": ""},
        )

    assert response.status_code == 422
    assert api.model.received_messages == []


def test_chat_with_invalid_model_output_returns_generic_error(
    fake_api: Any,
) -> None:
    invalid_output = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "AgentAnswer",
                "args": {"status": "unknown", "answer": ""},
                "id": "call-invalid-answer",
                "type": "tool_call",
            }
        ],
    )

    with fake_api([invalid_output]) as api:
        response = api.client.post(
            "/chat",
            json={"session_id": "session-1", "message": "Olá!"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": _GENERIC_ERROR_MESSAGE}
    assert "Traceback" not in response.text
    assert "StructuredOutputValidationError" not in response.text


def test_chat_sends_only_the_last_ten_history_messages(
    fake_api: Any,
    answer_message: Callable[..., AIMessage],
) -> None:
    history = [
        ChatMessage(
            role="user" if position % 2 == 0 else "assistant",
            content=f"mensagem-{position}",
        )
        for position in range(15)
    ]
    current_message = "E qual deles é o mais barato?"

    with fake_api([answer_message()]) as api:
        response = api.client.post(
            "/chat",
            json={
                "session_id": "session-1",
                "message": current_message,
                "history": [message.model_dump() for message in history],
            },
        )

    assert response.status_code == 200
    assert len(api.model.received_messages) == 1
    conversation = [
        message
        for message in api.model.received_messages[0]
        if message.type != "system"
    ]
    assert [message.content for message in conversation] == [
        message.content for message in history[-10:]
    ] + [current_message]


def test_health_returns_ok_when_agent_and_tools_are_loaded(fake_api: Any) -> None:
    with fake_api([]) as api:
        response = api.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
