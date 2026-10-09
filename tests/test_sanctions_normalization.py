"""
Tests for sanctions normalization adapter and architecture boundaries.

ADR-0008 D4 requires pinning representative normalization behavior
and guarding the unidirectional dependency from sanctions to entity_resolution.
"""

import ast
from pathlib import Path

import pytest

from meridian.agents.sanctions.errors import NormalizationVersionMismatch
from meridian.agents.sanctions.normalization import (
    EXPECTED_NORMALIZATION_VERSION,
    NORMALIZATION_VERSION,
    normalize_full_name,
)


def test_normalization_version_pin() -> None:
    """Verify normalization version is pinned to expected v1."""
    assert NORMALIZATION_VERSION == "v1"
    assert EXPECTED_NORMALIZATION_VERSION == "v1"


def test_normalization_goldens() -> None:
    """
    Pin representative normalization behavior per ADR-0008 D4:
    casefold, whitespace runs, NBSP-only input, and a fullwidth NFKC case.
    """
    # 1. NFKC fullwidth characters
    assert normalize_full_name("Ａｕｒｅｌｉｕｓ　Ｖａｎｃｅ") == "aurelius vance"
    assert normalize_full_name("Ｅｌｅｎａ") == "elena"

    # 2. Casefold (including German eszett)
    assert normalize_full_name("AURELIUS VANCE") == "aurelius vance"
    assert normalize_full_name("elena ROSTOVA") == "elena rostova"
    assert normalize_full_name("Stra\u00dfe") == "strasse"

    # 3. Whitespace runs and internal collapse
    assert normalize_full_name("  Aurelius   \t\n  Vance  ") == "aurelius vance"

    # 4. NBSP-only and empty inputs
    assert normalize_full_name("\u00a0\u00a0") == ""
    assert normalize_full_name("") == ""
    assert normalize_full_name(None) == ""

    # 5. Ideographic space only
    assert normalize_full_name("\u3000") == ""


def test_normalization_version_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a version mismatch between ER and F11 raises typed error."""
    import meridian.entity_resolution.matching as er_matching

    monkeypatch.setattr(er_matching, "NORMALIZATION_VERSION", "v2")
    with pytest.raises(NormalizationVersionMismatch) as exc_info:
        import importlib

        import meridian.agents.sanctions.normalization as norm_mod

        importlib.reload(norm_mod)

    assert "Expected normalization version 'v1'" in str(exc_info.value)

    # Restore module
    monkeypatch.setattr(er_matching, "NORMALIZATION_VERSION", "v1")
    importlib.reload(norm_mod)


def test_sanctions_architecture_boundaries() -> None:
    """
    Architecture guards per ADR-0008 D4:
    1. normalization.py is the ONLY sanctions module importing from entity_resolution.
    2. entity_resolution NEVER imports from agents.sanctions.
    """
    repo_root = Path(__file__).resolve().parent.parent
    sanctions_dir = repo_root / "src" / "meridian" / "agents" / "sanctions"
    er_dir = repo_root / "src" / "meridian" / "entity_resolution"

    # Check all sanctions files
    for py_file in sanctions_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "entity_resolution" in alias.name:
                        assert py_file.name == "normalization.py", (
                            f"Prohibited import of entity_resolution in "
                            f"{py_file.name}. Only normalization.py may import "
                            "from entity_resolution."
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module and "entity_resolution" in node.module:
                    assert py_file.name == "normalization.py", (
                        f"Prohibited import from entity_resolution in "
                        f"{py_file.name}. Only normalization.py may import "
                        "from entity_resolution."
                    )

    # Check all entity_resolution files
    for py_file in er_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "sanctions" not in alias.name, (
                        f"Prohibited import of sanctions in {py_file.name}."
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "sanctions" not in node.module, (
                        f"Prohibited import of sanctions in {py_file.name}."
                    )
