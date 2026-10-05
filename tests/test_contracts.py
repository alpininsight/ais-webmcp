"""One corpus through Python, CLI and Django; JS consumes the same cases."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from ais_webmcp.cli import main
from ais_webmcp.manifest import ToolSpec, WebmcpManifest
from ais_webmcp.operations import diff_manifests, doctor, export_manifest
from ais_webmcp.validate import validate_data

CASES = json.loads((Path(__file__).parent / "fixtures/cross-layer.json").read_text())


@pytest.mark.parametrize("entry", CASES, ids=lambda entry: entry["name"])
def test_cross_layer_corpus(entry, tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(entry["manifest"]))
    assert validate_data(entry["manifest"]).ok is entry["valid"]
    code = main(["validate", str(path), "--format", "json"])
    cli = json.loads(capsys.readouterr().out)
    out = StringIO()
    if entry["valid"]:
        call_command("webmcp_validate", str(path), "--format", "json", stdout=out)
    else:
        with pytest.raises(CommandError) as exc:
            call_command("webmcp_validate", str(path), "--format", "json", stdout=out)
        assert exc.value.returncode == code == 1
    assert json.loads(out.getvalue()) == cli


@pytest.mark.parametrize("command", ["validate", "list"])
def test_invalid_utf8_stable_error(command, tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff")
    assert main([command, str(path), "--format", "json"]) == 2
    assert "UTF-8" in capsys.readouterr().out
    with pytest.raises(CommandError) as exc:
        call_command("webmcp_validate", str(path))
    assert exc.value.returncode == 2


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


def test_second_django_and_static_profile(settings, tmp_path, capsys):
    settings.WEBMCP_PROFILES = ["tests.test_contracts.DocsProbeProfile"]
    path = tmp_path / "docs.json"
    call_command("webmcp_prepare", "--profile", "docs_probe", "--output", str(path))
    call_command("webmcp_validate", str(path))
    assert main(["validate", str(path), "--allow-profile", "docs_probe"]) == 0
    assert main(["doctor", str(path), "--allow-profile", "docs_probe", "--format", "json"]) == 0
    report = StringIO()
    call_command("webmcp_doctor", str(path), "--format", "json", stdout=report)
    browser_row = json.loads(report.getvalue())["checks"][-1]
    assert browser_row["check"] == "browser_support"
    assert browser_row["status"] == "unverified"
    assert "InsightUiWebmcp.status()" in browser_row["detail"]
    target = tmp_path / "docs.yaml"
    assert export_manifest(path, target, extra_profiles=("docs_probe",)).exit_code == 0
    assert diff_manifests(path, target, extra_profiles=("docs_probe",)) == ("", 0)
    assert export_manifest(path, target, extra_profiles=("docs_probe",)).exit_code == 1
    assert export_manifest(path, target, force=True, extra_profiles=("docs_probe",)).exit_code == 0


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


def test_django_client_fronts_share_init_export_diff(tmp_path):
    source = tmp_path / "manifest.json"
    target = tmp_path / "manifest.yaml"
    call_command("webmcp_init", "--output", str(source), "--static")
    assert (tmp_path / "register.js").is_file()
    call_command("webmcp_export", str(source), "--output", str(target))
    call_command("webmcp_diff", str(source), str(target))
    call_command("webmcp_status", "--manifest", str(source))
    with pytest.raises(CommandError) as exc:
        call_command("webmcp_init", "--output", str(source))
    assert exc.value.returncode == 1
