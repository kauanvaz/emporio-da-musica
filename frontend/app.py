import logging

import streamlit as st

from frontend.client import BackendClient
from frontend.config import Settings
from frontend.history import (
    add_message,
    get_history,
    get_session_id,
    reset_conversation,
)

logger = logging.getLogger(__name__)

_TITLE = "Empório da Música"
_DESCRIPTION = (
    "Atendimento virtual da Empório da Música. Pergunte sobre produtos, "
    "promoções, pedidos e políticas da loja."
)
_SPINNER_MESSAGE = "Preparando a resposta..."
_GENERIC_ERROR_MESSAGE = (
    "Não foi possível processar sua mensagem agora. Tente novamente em instantes."
)
_HUMAN_SUPPORT_MESSAGE = (
    "Este atendimento precisa da ajuda de uma pessoa da nossa equipe. "
    "Em breve, alguém continuará o atendimento por aqui."
)


def main() -> None:
    st.set_page_config(page_title=_TITLE, layout="centered")

    settings = Settings()
    client = BackendClient(settings.backend_url)

    st.title(_TITLE)
    st.write(_DESCRIPTION)

    with st.sidebar:
        if st.button("Nova conversa", use_container_width=True):
            reset_conversation()
            st.rerun()

    history = get_history()
    for message in history:
        with st.chat_message(message.role):
            st.markdown(message.content)

    prompt = st.chat_input("Digite sua mensagem")
    if not prompt or not prompt.strip():
        return

    previous_history = list(history)
    add_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        with st.spinner(_SPINNER_MESSAGE):
            answer = client.send_message(
                session_id=get_session_id(),
                message=prompt,
                history=previous_history,
            )
    except Exception:
        logger.exception("Could not complete the chat request.")
        st.error(_GENERIC_ERROR_MESSAGE)
        return

    add_message("assistant", answer.answer)
    with st.chat_message("assistant"):
        st.markdown(answer.answer)
        if answer.requires_human_support:
            st.warning(_HUMAN_SUPPORT_MESSAGE)


if __name__ == "__main__":
    main()
