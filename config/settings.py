"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM Configuration
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.0

    # Vector Store Configuration
    chroma_persist_directory: str = "./data/chroma"
    chroma_collection_name: str = "pe_documents"
    embedding_model: str = "text-embedding-3-small"

    # Application Configuration
    log_level: str = "INFO"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_k: int = 4
    cache_db_path: str = "./data/llm_cache.db"

    # Search Enhancement Flags
    enable_bm25: bool = True
    enable_llm_rewrite: bool = False
    enable_reranking: bool = False

    # Advanced Agent Flags
    enable_human_review: bool = False
    enable_entity_linking: bool = False

    # Regulatory Radar (SFC/HKMA polling)
    enable_regulatory_poll: bool = True
    regulatory_poll_hours: int = 24

    # Microsoft Graph mail (list mailbox + create drafts). Application
    # permissions Mail.Read + Mail.ReadWrite on the Azure app registration.
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_mailbox: str = ""  # userPrincipalName; falls back to OneDrive user


settings = Settings()
