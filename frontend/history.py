from typing import Literal
from uuid import uuid4

import streamlit as st

from frontend.client import ChatMessage

_HISTORY_KEY = "chat_history"
_SESSION_ID_KEY = "session_id"


def get_session_id() -> str:
    if _SESSION_ID_KEY not in st.session_state:
        st.session_state[_SESSION_ID_KEY] = str(uuid4())
    return st.session_state[_SESSION_ID_KEY]


def get_history() -> list[ChatMessage]:
    if _HISTORY_KEY not in st.session_state:
        st.session_state[_HISTORY_KEY] = []
    history = st.session_state[_HISTORY_KEY]
    if not isinstance(history, list):
        history = []
        st.session_state[_HISTORY_KEY] = history
    return history


def add_message(role: Literal["user", "assistant"], content: str) -> None:
    get_history().append(ChatMessage(role=role, content=content))


def reset_conversation() -> None:
    st.session_state[_HISTORY_KEY] = []
    st.session_state[_SESSION_ID_KEY] = str(uuid4())


__all__ = [
    "add_message",
    "get_history",
    "get_session_id",
    "reset_conversation",
]
