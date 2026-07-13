import importlib.util
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASR_MAIN_PATH = ROOT / "asr-service" / "app" / "main.py"


def load_asr_module():
    module_name = f"asr_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, ASR_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalize_transcript_removes_empty_segments():
    asr = load_asr_module()

    class Segment:
        def __init__(self, text):
            self.text = text

    assert asr.normalize_transcript([Segment(" hello "), Segment(""), Segment("world ")]) == "hello world"
