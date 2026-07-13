import importlib.util
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OCR_MAIN_PATH = ROOT / "ocr-service" / "app" / "main.py"


def load_ocr_module():
    module_name = f"ocr_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, OCR_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ocr_payload_uses_required_unlimited_ocr_settings():
    ocr = load_ocr_module()
    payload = ocr.build_ocr_payload(["data:image/png;base64,first", "data:image/png;base64,second"])

    assert payload["messages"][0]["content"][0]["text"] == "<image>Multi page parsing."
    assert payload["skip_special_tokens"] is False
    assert payload["vllm_xargs"] == {"ngram_size": 35, "window_size": 1024}


def test_clean_ocr_text_unwraps_reference_content():
    ocr = load_ocr_module()

    assert ocr.clean_ocr_text("<|ref|>Parsed text<|/ref|><|det|>bbox<|/det|>") == "Parsed text"
