"""#24 completeness on the current operations surface: no remote fetch, no token."""

import json
from pathlib import Path

from ais_webmcp.cli import main
from ais_webmcp.operations import doctor, export_manifest

SECRET = "TOKEN-DO-NOT-PRINT"
HEADER_SECRET = "HEADER-TOKEN-DO-NOT-PRINT"
CASES = json.loads((Path(__file__).parent / "fixtures/cross-layer.json").read_text())


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(CASES[0]["manifest"]), encoding="utf-8")
    return path


def test_doctor_refuses_http_and_https(capsys):
    for url in ("http://example.com/page", "https://example.com/a?token=secret"):
        assert main(["doctor", url, "--format", "json"]) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["exit_code"] == 2
        assert payload["checks"][0]["check"] == "target"
        assert "refusing to fetch a remote URL" in payload["checks"][0]["detail"]
        assert "secret" not in json.dumps(payload)
        assert "example.com" not in json.dumps(payload)


def test_doctor_accepts_file_url(tmp_path, capsys):
    manifest = _manifest(tmp_path)
    assert main(["doctor", manifest.as_uri(), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"][0]["status"] == "ok"


def test_doctor_redacts_tokens_and_notes_csp(tmp_path):
    manifest = _manifest(tmp_path)
    html = tmp_path / "index.html"
    html.write_text(
        f'<meta http-equiv="origin-trial" content="{SECRET}">'
        f'<meta http-equiv="Content-Security-Policy" content="script-src \'self\'">'
        f'<script src="https://cdn.example/lib.js"></script>\n'
        f"Origin-Trial: {HEADER_SECRET}\n",
        encoding="utf-8",
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    report, code = doctor(manifest, html=html)
    rendered = json.dumps(report)
    assert code == 0
    assert SECRET not in rendered
    assert HEADER_SECRET not in rendered
    by_check = {row["check"]: row for row in report["checks"]}
    assert by_check["origin_trial_configuration"]["status"] == "present"
    assert "token redacted" in by_check["origin_trial_configuration"]["detail"]
    assert str(len(SECRET)) in by_check["origin_trial_configuration"]["detail"]
    assert str(len(HEADER_SECRET)) in by_check["origin_trial_configuration"]["detail"]
    assert by_check["csp_same_origin"]["status"] == "ok"
    assert "not rewritten" in by_check["csp_same_origin"]["detail"]
    assert "'self'" in by_check["csp_same_origin"]["detail"]
    assert by_check["third_party_scripts"]["status"] == "warning"
    assert "cdn.example" in by_check["third_party_scripts"]["detail"]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_export_tools_and_snippet_hide_tokens(tmp_path, capsys):
    manifest = _manifest(tmp_path)
    tools = tmp_path / "tools.json"
    snippet = tmp_path / "snippet.html"
    assert main(["export", str(manifest), "--kind", "tools", "--output", str(tools)]) == 0
    listed = json.loads(tools.read_text(encoding="utf-8"))
    assert [tool["id"] for tool in listed["tools"]] == ["probe"]
    assert main(["export", str(manifest), "--kind", "snippet", "--output", str(snippet)]) == 0
    body = snippet.read_text(encoding="utf-8")
    assert 'src="register.js"' in body
    assert "content=" not in body
    assert SECRET not in body
    assert "eyJ" not in body
    assert "never includes a token" in body
    assert main(["export", str(manifest), "--kind", "snippet", "--output", str(snippet)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().out
    forced = export_manifest(manifest, snippet, force=True, kind="snippet")
    assert forced.exit_code == 0
    assert SECRET not in snippet.read_text(encoding="utf-8")
