import os
from dataclasses import dataclass, field


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


@dataclass(frozen=True)
class AppConfig:
    recommendations_enabled: bool = True
    book_medicine_matching_enabled: bool = False
    product_scope_mode: str = "team_confirmed_catalog"
    planned_product_count: int = 30
    llm_provider: str = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    voice_enabled: bool = True
    whisper_model: str = "base"
    piper_en_model_path: str = "models/piper/en_US-lessac-medium.onnx"
    piper_de_model_path: str = "models/piper/de_DE-thorsten-medium.onnx"
    app_environment: str = "development"
    raw_health_logging_enabled: bool = False
    catalog_admin_token: str | None = None
    product_catalog_path: str = "instance/product_catalog.json"
    protocol_catalog_path: str = "instance/protocols.json"
    pinecone_index_name: str | None = None
    pinecone_retrieval_mode: str = "approved_sources"
    pinecone_book_source: str = "data\\Medical_book.pdf"
    pinecone_api_key: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)
    inventory_api_url: str | None = None
    inventory_api_token: str | None = field(default=None, repr=False)
    supabase_url: str | None = None
    supabase_service_role_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.pinecone_retrieval_mode not in {"approved_sources", "medical_book"}:
            raise ValueError("PINECONE_RETRIEVAL_MODE must be approved_sources or medical_book.")
        if self.pinecone_retrieval_mode == "medical_book" and not self.pinecone_book_source.strip():
            raise ValueError("PINECONE_BOOK_SOURCE must identify the indexed book.")
        if self.app_environment not in {"development", "test", "staging", "production"}:
            raise ValueError("APP_ENV must be development, test, staging, or production.")

    @classmethod
    def from_environment(cls) -> "AppConfig":
        config = cls(
            recommendations_enabled=_boolean("RECOMMENDATIONS_ENABLED", True),
            book_medicine_matching_enabled=_boolean("BOOK_MEDICINE_MATCHING_ENABLED", False),
            product_scope_mode=os.getenv(
                "PRODUCT_SCOPE_MODE", "team_confirmed_catalog"
            ),
            planned_product_count=int(os.getenv("PLANNED_PRODUCT_COUNT", "30")),
            llm_provider=os.getenv("LLM_PROVIDER", "gemini").lower(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            voice_enabled=_boolean("VOICE_ENABLED", True),
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            piper_en_model_path=os.getenv(
                "PIPER_EN_MODEL_PATH",
                "models/piper/en_US-lessac-medium.onnx",
            ),
            piper_de_model_path=os.getenv(
                "PIPER_DE_MODEL_PATH",
                "models/piper/de_DE-thorsten-medium.onnx",
            ),
            app_environment=os.getenv("APP_ENV", "development").strip().lower(),
            raw_health_logging_enabled=_boolean(
                "RAW_HEALTH_LOGGING_ENABLED", False
            ),
            catalog_admin_token=os.getenv("CATALOG_ADMIN_TOKEN") or None,
            product_catalog_path=os.getenv(
                "PRODUCT_CATALOG_PATH", "instance/product_catalog.json"
            ),
            protocol_catalog_path=os.getenv(
                "PROTOCOL_CATALOG_PATH", "instance/protocols.json"
            ),
            pinecone_index_name=os.getenv("PINECONE_INDEX_NAME") or None,
            pinecone_retrieval_mode=os.getenv("PINECONE_RETRIEVAL_MODE", "approved_sources").strip().lower(),
            pinecone_book_source=os.getenv("PINECONE_BOOK_SOURCE", "data\\Medical_book.pdf"),
            pinecone_api_key=os.getenv("PINECONE_API_KEY") or None,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            inventory_api_url=os.getenv("INVENTORY_API_URL") or None,
            inventory_api_token=os.getenv("INVENTORY_API_TOKEN") or None,
            supabase_url=os.getenv("SUPABASE_URL") or None,
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None,
        )
        if config.llm_provider != "gemini":
            raise ValueError("This application is configured to use the Gemini provider.")
        if config.product_scope_mode != "team_confirmed_catalog":
            raise ValueError("Unsupported PRODUCT_SCOPE_MODE.")
        if config.planned_product_count != 30:
            raise ValueError("PLANNED_PRODUCT_COUNT must remain the Part 2 catalog count of 30.")
        if config.raw_health_logging_enabled:
            raise ValueError("Raw health logging is not supported.")
        return config
