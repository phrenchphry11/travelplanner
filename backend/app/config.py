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
    anthropic_api_key: str = ""
    worker_poll_seconds: float = 3.0

    @property
    def jwks_url(self) -> str:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
