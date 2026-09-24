from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./dev.db"
    # Clerk: the issuer is your Clerk frontend API URL, e.g. https://xyz.clerk.accounts.dev
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    cors_origins: str = "http://localhost:5173"
    # Frontend origins allowed in a Clerk token's azp claim. Empty means reuse
    # cors_origins, since the sites allowed to call the API are the same sites
    # allowed to request tokens for it.
    authorized_parties: str = ""
    anthropic_api_key: str = ""
    # Comma-separated emails that can see the internal admin view (agent costs).
    admin_emails: str = ""
    intake_model: str = "claude-opus-5"
    research_model: str = "claude-opus-5"
    # Tuned 2026-09-16: 8 searches at medium effort cost ~$0.85 per gap, mostly
    # search-result input tokens. Fewer searches and low effort keep Opus 5 quality
    # at lower cost; both are overridable via env.
    research_effort: str = "low"
    research_max_searches_per_request: int = 5
    research_max_turns: int = 4
    # Estimated USD per million tokens / per search, for ResearchJob.cost_usd.
    # Claude Opus 5 list prices; fallback-model turns are billed at their own rates.
    price_input_per_mtok: float = 5.0
    price_output_per_mtok: float = 25.0
    price_cache_write_per_mtok: float = 6.25
    price_cache_read_per_mtok: float = 0.5
    price_per_search: float = 0.01
    # OpenStreetMap Nominatim. Policy: https://operations.osmfoundation.org/policies/nominatim/
    # Max 1 req/s, identifying User-Agent, cache results. Swap the URL to change provider.
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "travelplanner/0.1 (+https://github.com/phrenchphry11/travelplanner)"
    worker_poll_seconds: float = 3.0

    @property
    def jwks_url(self) -> str:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def authorized_party_list(self) -> list[str]:
        raw = self.authorized_parties or self.cors_origins
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
