"""One corpus through Python and CLI; JS consumes the same cases."""

import json
from pathlib import Path

import pytest

from ais_webmcp.cli import main
from ais_webmcp.manifest import ToolSpec, WebmcpManifest
from ais_webmcp.operations import doctor, export_manifest
from ais_webmcp.validate import validate_data

CASES = json.loads((Path(__file__).parent / "fixtures/cross-layer.json").read_text())


@pytest.mark.parametrize("entry", CASES, ids=lambda entry: entry["name"])
def test_cross_layer_corpus(entry, tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(entry["manifest"]))
    assert validate_data(entry["manifest"]).ok is entry["valid"]
    code = main(["validate", str(path), "--format", "json"])
    cli = json.loads(capsys.readouterr().out)
    assert code == (0 if entry["valid"] else 1)
    assert cli["ok"] is entry["valid"]


@pytest.mark.parametrize("command", ["validate", "list"])
def test_invalid_utf8_stable_error(command, tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff")
    assert main([command, str(path), "--format", "json"]) == 2
    assert "UTF-8" in capsys.readouterr().out


class DocsProbeProfile:
    name = "docs_probe"

    def describe_tools(self):
        return (
            ToolSpec(
                "search_components", "Search components", "Search public components", read_only=True
            ),
        )

    def describe_anchors(self):
        return ()

    def build_manifest(self, *, version="1"):
        return WebmcpManifest(self.name, version, self.describe_tools())


def test_doctor_redacts_origin_trial_and_is_readonly(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(CASES[0]["manifest"]))
    html = tmp_path / "index.html"
    html.write_text(
        '<meta http-equiv="origin-trial" content="TOKEN-DO-NOT-PRINT"><meta http-equiv="Content-Security-Policy" content="script-src \'self\'">'
    )
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    report, code = doctor(manifest, html=html)
    assert code == 0
    assert "TOKEN-DO-NOT-PRINT" not in json.dumps(report)
    assert report["checks"][2]["status"] == "present"
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_export_never_follows_symlink_even_with_force(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(CASES[0]["manifest"]))
    protected = tmp_path / "protected.json"
    protected.write_text("keep this")
    link = tmp_path / "linked.json"
    link.symlink_to(protected)
    assert export_manifest(source, link, force=True).exit_code == 2
    assert protected.read_text() == "keep this"
