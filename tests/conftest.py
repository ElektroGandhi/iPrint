"""Load the pure modules of the integration without Home Assistant installed.

protocol, render and printer need only the standard library and Pillow. Everything else needs a running HA and is
covered by the hassfest/HACS checks in CI.
"""
import importlib.util
import sys
import types
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "phomemo"

_pkg = types.ModuleType("phomemo")
_pkg.__path__ = [str(PKG)]
sys.modules["phomemo"] = _pkg
for _name in ("const", "protocol", "render", "printer"):
    _spec = importlib.util.spec_from_file_location(f"phomemo.{_name}", PKG / f"{_name}.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"phomemo.{_name}"] = _mod
    _spec.loader.exec_module(_mod)
