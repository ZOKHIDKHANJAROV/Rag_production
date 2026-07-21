from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    embedding_concurrency: int
    internal_service_token: str
    service_auth_header: str = "X-Service-Token"

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            embedding_concurrency=int(os.getenv("EMBEDDING_CONCURRENCY", "4")),
            internal_service_token=os.getenv("INTERNAL_SERVICE_TOKEN", ""),
        )


settings = Settings.from_environment()
