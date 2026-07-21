from datetime import datetime, timezone
import hashlib
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.document_processing import (
    chunk_document,
    derive_document_title,
    extract_text_from_docx,
    extract_text_from_pdf,
    normalize_document_date,
)


class DocumentIngestionService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    def _headers(self) -> dict[str, str]:
        if not self.settings.internal_service_token:
            return {}
        return {
            self.settings.service_auth_header: self.settings.internal_service_token,
        }

    async def upload(
        self,
        file_bytes: bytes,
        filename: str,
        scope_key: str,
        owner_username: str | None,
        knowledge_base: str,
        document_title: str | None,
        document_date: str | None,
    ) -> dict:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file")

        native_text, extraction_error = self._extract_native_text(file_bytes, filename)
        text = native_text
        extraction_engine = "native"
        if self._should_use_ocr(filename, text, scope_key, len(file_bytes)):
            try:
                ocr_text = await self._extract_ocr(file_bytes, filename)
            except (HTTPException, httpx.HTTPError) as error:
                if not text.strip():
                    raise HTTPException(
                        status_code=503,
                        detail=f"OCR extraction unavailable: {str(error)}",
                    ) from error
            else:
                if ocr_text.strip():
                    text = ocr_text
                    extraction_engine = "Unlimited-OCR"

        if not text.strip():
            if extraction_error:
                raise HTTPException(
                    status_code=422,
                    detail=f"Text extraction failed: {str(extraction_error)}",
                )
            raise HTTPException(status_code=422, detail="No text extracted from file")

        title = (document_title or derive_document_title(filename, text)).strip()[:160]
        document_type = Path(filename).suffix.lower().lstrip(".") or "unknown"
        detected_date = normalize_document_date(document_date) or normalize_document_date(
            f"{filename}\n{text[:4000]}"
        )
        chunks, sections = chunk_document(text, title)
        if not chunks:
            raise HTTPException(status_code=422, detail="No chunks generated")

        document_id = hashlib.sha256(file_bytes).hexdigest()
        uploaded_at = datetime.now(timezone.utc).isoformat()
        try:
            response = await self.client.post(
                f"{self.settings.vector_service_url}/index",
                json={
                    "texts": chunks,
                    "document_id": document_id,
                    "filename": filename,
                    "title": title,
                    "sections": sections,
                    "document_date": detected_date,
                    "document_type": document_type,
                    "uploaded_at": uploaded_at,
                    "scope_key": scope_key,
                    "owner_username": owner_username,
                    "knowledge_base": knowledge_base,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise HTTPException(
                status_code=502,
                detail={"error": "Vector service failed", "details": error.response.text},
            ) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503,
                detail=f"Vector service unreachable: {str(error)}",
            ) from error

        return {
            "status": "indexed",
            "document_id": document_id,
            "chunks": len(chunks),
            "scope_key": scope_key,
            "knowledge_base": knowledge_base,
            "owner_username": owner_username,
            "title": title,
            "document_date": detected_date,
            "document_type": document_type,
            "uploaded_at": uploaded_at,
            "extraction_engine": extraction_engine,
        }

    def _extract_native_text(self, file_bytes: bytes, filename: str) -> tuple[str, Exception | None]:
        lowered = filename.lower()
        try:
            if lowered.endswith(".pdf"):
                return extract_text_from_pdf(file_bytes), None
            if lowered.endswith(".docx"):
                return extract_text_from_docx(file_bytes), None
            if lowered.endswith((".txt", ".md")):
                return file_bytes.decode("utf-8", errors="ignore"), None
            if lowered.endswith((".png", ".jpg", ".jpeg", ".webp")):
                return "", None
            raise HTTPException(status_code=415, detail="Unsupported file type")
        except HTTPException:
            raise
        except Exception as error:
            return "", error

    def _should_use_ocr(self, filename: str, text: str, scope_key: str, file_size: int) -> bool:
        return (
            self.settings.ocr_enabled
            and filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp"))
            and scope_key.startswith("user:")
            and file_size > 0
            and not text.strip()
        )

    async def _extract_ocr(self, file_bytes: bytes, filename: str) -> str:
        response = await self.client.post(
            self.settings.ocr_service_url,
            files={"file": (filename, file_bytes, "application/octet-stream")},
            data={"filename": filename},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json().get("text", "")
