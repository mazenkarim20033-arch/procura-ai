from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str | None = None

    # AI (provider wiring lands in a later milestone; "mock" needs no credentials)
    llm_provider: str = "mock"  # mock | groq | openai_compat
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None  # groq defaults to https://api.groq.com/openai/v1
    # Optional USD prices per million tokens. Cost is only estimated when BOTH are set; none are assumed.
    llm_price_in_per_m: float | None = None
    llm_price_out_per_m: float | None = None
    embedding_provider: str = "fastembed"  # fastembed | hashing (test-only, not semantic)
    # Chosen on dev-split MRR in evals/reports/retrieval_2026-11-13_498ec60.json (bge-small was within
    # noise; MiniLM is smaller and faster). Changing the model REQUIRES re-indexing and re-tuning the gate.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_cache_dir: str | None = None  # fastembed defaults to the OS temp dir, which can be wiped
    embedding_query_prefix: bool = True  # BGE-style instruction; only applied to bge models
    retrieval_mode: str = "dense"  # dense beat hybrid-RRF and FTS on the benchmark; hybrid stays available
    rerank_enabled: bool = False  # cross-encoder gave no gain on the benchmark and costs latency
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Relevance gate for policy QUESTIONS (POST /policies/search): minimum cosine similarity of the best hit.
    # Tuned for MiniLM-L6-v2 on the dev split (evals/reports/gate_*.json); NOT portable to other models.
    relevance_min_similarity: float = 0.385
    # Minimum similarity for a clause to be SHOWN to the LLM stage. Deliberately lower than the gate above:
    # request-style queries ("Purchase of laptops from X for N USD") score about 0.36 against judgement
    # clauses, so the 0.385 gate switched the stage off in 36 of 40 benchmark scenarios. UNCALIBRATED
    # (no relevance labels for this query type); the prompt tells the model to stay silent when nothing
    # applies and the evidence verifier drops unsupported claims.
    llm_stage_min_similarity: float = 0.30

    cors_origins: list[str] = ["http://localhost:5173"]
    # Public-demo switch. Identities are demo headers, not real authentication, so an internet-facing instance must
    # not accept writes: with READ_ONLY=true every request that is not GET/HEAD/OPTIONS is refused (403), except
    # POST /policies/search, which only reads policies (it writes one retrieval-log row).
    read_only: bool = False

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_driver(cls, v: str | None) -> str | None:
        if v is None:
            return v
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_mock_ai(self) -> bool:
        return self.llm_provider == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
