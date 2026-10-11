"""Atomic Design tree for doctor --tree (#20)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ais_webmcp.operations import atomic_tree, doctor, format_atomic_tree

REPO = Path(__file__).resolve().parents[1]
WEBPAGE = REPO / "tests" / "fixtures" / "manifests" / "valid" / "webpage.json"


@pytest.mark.unit
def test_atomic_tree_groups_webpage_molecules() -> None:
    data = json.loads(WEBPAGE.read_text(encoding="utf-8"))
    tree = atomic_tree(data)
    assert tree["organism"] == "webpage"
    names = [m["name"] for m in tree["molecules"]]
    assert "navigation" in names
    assert "content" in names
    assert "legal_contact" in names
    assert "consequential" in names
    cons = next(m for m in tree["molecules"] if m["name"] == "consequential")
    assert any(a["id"] == "subscribe_newsletter" and a["enabled"] is False for a in cons["atoms"])
    text = format_atomic_tree(tree)
    assert "organism: webpage" in text
    assert "molecule: navigation" in text
    assert "atom: list_sections" in text


@pytest.mark.unit
def test_doctor_tree_flag_includes_tree_key() -> None:
    report, code = doctor(str(WEBPAGE), tree=True)
    assert code in (0, 1)
    assert report["tree"]["organism"] == "webpage"
