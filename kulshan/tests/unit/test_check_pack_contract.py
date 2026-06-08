"""Each mf_<name> check pack must expose ``run_scan`` at the top level.

This test locks the contract that lets Kulshan adapters be thin passthroughs
and that lets the orchestrator call every pack uniformly.
"""
from __future__ import annotations

import importlib
import inspect

import pytest

from kulshan.orchestrator import TOOL_ORDER

CHECK_PACK_MODULES = sorted(f"kulshan.checks.{key}" for key in TOOL_ORDER)


@pytest.mark.parametrize("module_name", CHECK_PACK_MODULES)
def test_pack_imports(module_name: str):
    module = importlib.import_module(module_name)
    assert module is not None


@pytest.mark.parametrize("module_name", CHECK_PACK_MODULES)
def test_pack_exposes_run_scan(module_name: str):
    module = importlib.import_module(module_name)
    assert hasattr(module, "run_scan"), f"{module_name} must expose top-level run_scan"
    assert callable(module.run_scan), f"{module_name}.run_scan must be callable"


@pytest.mark.parametrize("module_name", CHECK_PACK_MODULES)
def test_pack_run_scan_accepts_quick_kwarg(module_name: str):
    module = importlib.import_module(module_name)
    sig = inspect.signature(module.run_scan)
    assert "quick" in sig.parameters, (
        f"{module_name}.run_scan must accept `quick` kwarg; "
        f"got params={list(sig.parameters)}"
    )


@pytest.mark.parametrize("module_name", CHECK_PACK_MODULES)
def test_pack_run_scan_accepts_extra_kwargs(module_name: str):
    """run_scan must tolerate extra kwargs (so the orchestrator can pass profile etc.
    to every pack uniformly without special-casing)."""
    module = importlib.import_module(module_name)
    sig = inspect.signature(module.run_scan)
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    assert has_var_keyword, (
        f"{module_name}.run_scan must accept **kwargs so the orchestrator can call "
        f"all packs uniformly; got params={list(sig.parameters)}"
    )


@pytest.mark.parametrize("module_name", CHECK_PACK_MODULES)
def test_pack_exposes_version(module_name: str):
    module = importlib.import_module(module_name)
    assert hasattr(module, "__version__"), f"{module_name} must expose __version__"
    assert isinstance(module.__version__, str)
