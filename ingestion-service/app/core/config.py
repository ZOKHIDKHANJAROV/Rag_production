from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    vector_service_url: str
    request_timeout: int
    http_max_connections: int
    http_max_keepalive: int
    ocr_enabled: bool
    ocr_service_url: str
    internal_service_token: str
    service_auth_header: str = "X-Service-Token"

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            vector_service_url=os.getenv("VECTOR_SERVICE_URL", "http://embedding-service:8001"),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "300")),
            http_max_connections=int(os.getenv("INGESTION_HTTP_MAX_CONNECTIONS", "100")),
            http_max_keepalive=int(os.getenv("INGESTION_HTTP_MAX_KEEPALIVE", "20")),
            ocr_enabled=os.getenv("OCR_ENABLED", "false").lower() == "true",
            ocr_service_url=os.getenv("OCR_SERVICE_URL", "http://ocr-service:8006/extract"),
            internal_service_token=os.getenv("INTERNAL_SERVICE_TOKEN", ""),
        )


settings = Settings.from_environment()
