import importlib.util
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = ROOT / "ingestion-service"
INGESTION_MAIN_PATH = INGESTION_ROOT / "app" / "main.py"


def load_ingestion_module():
    module_name = f"ingestion_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, INGESTION_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_document_metadata_extracts_title_date_and_sections():
    ingestion = load_ingestion_module()
    text = "# Safety policy\nUpdated 2025-06-18\n\n## Scope\nWear a helmet."

    title = ingestion.derive_document_title("safety_policy.md", text)
    chunks, sections = ingestion.chunk_document(text, title)

    assert title == "Safety policy"
    assert ingestion.normalize_document_date(text) == "2025-06-18"
    assert chunks == ["Updated 2025-06-18", "Wear a helmet."]
    assert sections == ["Safety policy", "Scope"]


def test_ocr_is_used_only_for_short_scanned_content(monkeypatch):
    ingestion = load_ingestion_module()
    monkeypatch.setattr(ingestion, "OCR_ENABLED", True)
    monkeypatch.setattr(ingestion, "OCR_MIN_TEXT_CHARS", 80)

    assert ingestion.should_use_ocr("scan.pdf", "too short")
    assert ingestion.should_use_ocr("receipt.png", "")
    assert not ingestion.should_use_ocr("report.docx", "")
    assert not ingestion.should_use_ocr("report.pdf", "x" * 80)
