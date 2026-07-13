import importlib.util
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TTS_MAIN_PATH = ROOT / "tts-service" / "app" / "main.py"


def load_tts_module():
    module_name = f"tts_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, TTS_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_public_profile_does_not_expose_reference_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_PROFILE_PATH", str(tmp_path / "profile.json"))
    monkeypatch.setenv("TTS_REFERENCE_PATH", str(tmp_path / "reference.wav"))
    tts = load_tts_module()

    assert tts.public_profile({"enabled": True, "mode": "sft", "speaker_id": "narrator", "prompt_text": ""}) == {
        "enabled": True,
        "mode": "sft",
        "speaker_id": "narrator",
        "prompt_text": "",
        "has_reference": False,
    }
