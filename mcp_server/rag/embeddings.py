from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from mcp_server.config import Settings


class EmbeddingConfigurationError(RuntimeError):
    pass


def create_policy_embeddings(settings: Settings) -> OpenAIEmbeddings:
    if settings.openai_api_key is None:
        raise EmbeddingConfigurationError(
            "OPENAI_API_KEY is required to generate or query policy embeddings."
        )
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=SecretStr(settings.openai_api_key),
    )


__all__ = ["EmbeddingConfigurationError", "create_policy_embeddings"]
