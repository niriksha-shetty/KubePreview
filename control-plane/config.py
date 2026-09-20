from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GITHUB_WEBHOOK_SECRET: str = "dev-secret"
    BASE_DOMAIN: str = "127.0.0.1.nip.io"
    CLUSTER_IN_CLUSTER: bool = False
    TTL_HOURS: int = 2
    MANIFESTS_DIR: Path = Path(__file__).resolve().parent.parent / "manifests"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
