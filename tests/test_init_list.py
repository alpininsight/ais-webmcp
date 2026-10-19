"""ais-webmcp init and list (issue #20, pulled forward with validate)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ais_webmcp.scaffold import STARTER_NOTE, init_manifest, starter_manifest
from webmcp_manifest.validate import validate_path

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_JSON = REPO_ROOT / "tests" / "fixtures" / "manifests" / "valid" / "webpage.json"
INVALID = REPO_ROOT / "tests" / "fixtures" / "manifests" / "invalid" / "duplicate-id.json"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    return subprocess.run(
        [sys.executable, "-m", "ais_webmcp", *args],
        cwd=cwd or REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_starter_matches_webpage_fixture_and_stays_default_off() -> None:
    fixture = json.loads(VALID_JSON.read_text(encoding="utf-8"))
    starter = starter_manifest()
    assert starter["profile"] == fixture["profile"] == "webpage"
    assert starter["version"] == fixture["version"] == "1"
    assert starter["anchors"] == fixture["anchors"]
    assert starter["tools"] == fixture["tools"]
    assert starter["notes"][:-1] == fixture["notes"]
    assert starter["notes"][-1] == STARTER_NOTE
    subscribe = next(tool for tool in starter["tools"] if tool["id"] == "subscribe_newsletter")
    assert subscribe["consequential"] is True
    assert subscribe["enabled"] is False
    assert not any(
        str(tool.get("id", "")).startswith("subscribe_") and tool.get("enabled") is True
        for tool in starter["tools"]
    )


@pytest.mark.unit
def test_init_writes_yaml_that_validates(tmp_path: Path) -> None:
    target = tmp_path / "manifest.yaml"
    result = init_manifest(target)
    assert result.exit_code == 0, result.report
    assert target.is_file()
    parsed = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert parsed == starter_manifest()
    checked = validate_path(target)
    assert checked.ok, checked.issues
    assert "subscribe_newsletter" in target.read_text(encoding="utf-8")
    assert "Origin Trial token" in target.read_text(encoding="utf-8")
    assert "{% webmcp_assets %}" in result.report


@pytest.mark.unit
def test_init_json_output_validates(tmp_path: Path) -> None:
    target = tmp_path / "webmcp.manifest.json"
    result = init_manifest(target)
    assert result.exit_code == 0, result.report
    assert json.loads(target.read_text(encoding="utf-8")) == starter_manifest()
    assert validate_path(target).ok


@pytest.mark.unit
def test_init_directory_output_and_refuse_without_force(tmp_path: Path) -> None:
    result = init_manifest(tmp_path)
    manifest = tmp_path / "manifest.yaml"
    assert result.exit_code == 0, result.report
    assert manifest.is_file()
    original = manifest.read_text(encoding="utf-8")

    again = init_manifest(tmp_path)
    assert again.exit_code == 1
    assert "refusing to overwrite" in again.report
    assert manifest.read_text(encoding="utf-8") == original

    forced = init_manifest(tmp_path, force=True)
    assert forced.exit_code == 0, forced.report
    assert "unchanged:" in forced.report
    assert manifest.read_text(encoding="utf-8") == original


@pytest.mark.unit
def test_init_force_prints_diff_summary(tmp_path: Path) -> None:
    target = tmp_path / "manifest.yaml"
    assert init_manifest(target).exit_code == 0
    target.write_text("profile: webpage\nversion: '1'\ntools: []\n", encoding="utf-8")
    forced = init_manifest(target, force=True)
    assert forced.exit_code == 0, forced.report
    assert "force: replacing" in forced.report
    assert "--- a/manifest.yaml" in forced.report
    assert validate_path(target).ok


@pytest.mark.unit
def test_init_static_stubs_have_no_token(tmp_path: Path) -> None:
    result = init_manifest(tmp_path / "manifest.yaml", static=True)
    assert result.exit_code == 0, result.report
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    script = (tmp_path / "webmcp.js").read_text(encoding="utf-8")
    assert 'href="manifest.yaml"' in index
    assert "webmcp.js" in index
    assert 'http-equiv="' not in index
    assert "content=" not in index
    assert "never includes a token" in index
    assert "eyJ" not in index
    assert "eyJ" not in script
    assert "function registerTool" not in script
    assert "registerFromManifest(" not in script
    assert "document.modelContext" in script
    assert "enabled: false" in script or "enabled: false" in index or "enabled false" in script
    assert validate_path(tmp_path / "manifest.yaml").ok

    blocked = init_manifest(tmp_path / "manifest.yaml", static=True)
    assert blocked.exit_code == 1
    assert "index.html" in blocked.report
    assert "webmcp.js" in blocked.report


@pytest.mark.unit
def test_init_rejects_bad_suffix(tmp_path: Path) -> None:
    result = init_manifest(tmp_path / "manifest.txt")
    assert result.exit_code == 2
    assert not (tmp_path / "manifest.txt").exists()


@pytest.mark.unit
def test_cli_init_and_list_round_trip(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    created = _run("init", "--output", str(manifest), "--static", cwd=tmp_path)
    assert created.returncode == 0, created.stderr + created.stdout
    assert "wrote" in created.stdout

    checked = _run("validate", str(manifest))
    assert checked.returncode == 0, checked.stderr + checked.stdout

    listed = _run("list", str(manifest))
    assert listed.returncode == 0, listed.stderr + listed.stdout
    assert "name: List sections" in listed.stdout
    assert "description: List available page section anchors on this host." in listed.stdout
    assert "enabled: (omitted)" in listed.stdout
    assert "subscribe_newsletter" in listed.stdout
    assert "enabled: false" in listed.stdout
    assert "annotations: readOnlyHint=true" in listed.stdout
    assert "annotations: readOnlyHint=false, consequentialHint=true" in listed.stdout

    as_json = _run("list", "--format", "json", str(manifest))
    assert as_json.returncode == 0, as_json.stderr + as_json.stdout
    payload = json.loads(as_json.stdout)
    assert payload["profile"] == "webpage"
    by_id = {tool["id"]: tool for tool in payload["tools"]}
    assert by_id["list_sections"]["enabled"] is None
    assert by_id["list_sections"]["annotations"] == {"readOnlyHint": True}
    assert by_id["subscribe_newsletter"]["enabled"] is False
    assert by_id["subscribe_newsletter"]["description"].startswith("Subscribe")
    assert by_id["subscribe_newsletter"]["annotations"]["consequentialHint"] is True

    refused = _run("init", "--output", str(manifest), cwd=tmp_path)
    assert refused.returncode == 1
    assert "refusing to overwrite" in refused.stdout


@pytest.mark.unit
def test_mixed_list_keeps_output_schema_findings(tmp_path: Path) -> None:
    """A valid file listed beside an invalid one still exposes low findings."""
    good = tmp_path / "good.json"
    tool = json.loads(VALID_JSON.read_text(encoding="utf-8"))
    tool["tools"] = [tool["tools"][0]]
    good.write_text(json.dumps(tool), encoding="utf-8")
    listed = _run("list", "--format", "json", str(good), str(INVALID))
    assert listed.returncode == 1, listed.stderr + listed.stdout
    payload = json.loads(listed.stdout)
    assert payload[0]["ok"] is True
    assert payload[0]["findings"][0]["code"] == "missing_output_schema"
    assert payload[0]["findings"][0]["severity"] == "low"
    assert payload[1]["ok"] is False


@pytest.mark.unit
def test_list_fixture_and_invalid_exits() -> None:
    ok = _run("list", str(VALID_JSON), "--format", "json")
    assert ok.returncode == 0, ok.stderr + ok.stdout
    payload = json.loads(ok.stdout)
    assert len(payload["tools"]) == 9

    bad = _run("list", str(INVALID))
    assert bad.returncode == 1
    assert "duplicate tool id" in bad.stdout
    assert "name: List sections" not in bad.stdout

    missing = _run("list", str(REPO_ROOT / "tests" / "no-such-manifest.yaml"))
    assert missing.returncode == 2


@pytest.mark.unit
def test_init_and_list_import_do_not_load_django() -> None:
    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / "src"),
        ]
    )
    code = (
        "import sys\n"
        "import ais_webmcp.cli\n"
        "import ais_webmcp.scaffold\n"
        "import ais_webmcp.listing\n"
        "assert 'django' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
