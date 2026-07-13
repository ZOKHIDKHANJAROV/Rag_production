import importlib.util
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ZUP_MAIN_PATH = ROOT / "zup-service" / "app" / "main.py"


def load_zup_module():
    module_name = f"zup_main_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, ZUP_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_zup_proxy_normalizes_known_employee_fields_only():
    zup = load_zup_module()
    employee = zup.normalize_employee({"name": "Ada", "pinfl": "123", "unexpected": "ignored"})

    assert employee == {"pinfl": "123", "name": "Ada"}


def test_zup_proxy_accepts_common_list_wrappers():
    zup = load_zup_module()

    assert zup.extract_records({"value": [{"name": "Ada"}]}) == [{"name": "Ada"}]
