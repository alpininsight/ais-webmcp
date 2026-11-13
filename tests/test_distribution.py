"""Normal wheel/sdist installs of the core package outside the checkout."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def isolated_environment():
    """Keep interpreter/transport paths, without inheriting application credentials."""
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "UV_CACHE_DIR",
        # setup-python's Linux builds need this to resolve libpython. Do not
        # inherit Python import paths or settings from the source checkout.
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def test_isolated_environment_keeps_runtime_paths_without_host_configuration(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/runner/python/lib")
    monkeypatch.setenv("PYTHONPATH", "/host/source")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "host.settings")
    monkeypatch.setenv("SETUPTOOLS_SCM_PRETEND_VERSION", "9.9.9")
    monkeypatch.setenv("HOST_TEST_CREDENTIAL", "dummy-test-value")
    env = isolated_environment()
    assert env["LD_LIBRARY_PATH"] == "/runner/python/lib"
    for key in (
        "PYTHONPATH",
        "DJANGO_SETTINGS_MODULE",
        "SETUPTOOLS_SCM_PRETEND_VERSION",
        "HOST_TEST_CREDENTIAL",
    ):
        assert key not in env


def run(*args, cwd=None, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_pypi_metadata_urls_and_apache_license():
    """PyPI project URLs point at this public repository. License stays Apache-2.0."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert "License :: OSI Approved :: Apache Software License" in project["classifiers"]
    # The library is not fully typed (several public helpers are unannotated),
    # so it must not claim Typing :: Typed.
    assert "Typing :: Typed" not in project["classifiers"]
    assert not (ROOT / "src" / "ais_webmcp" / "py.typed").is_file()
    urls = project["urls"]
    assert urls["Homepage"] == "https://insight-ui-webmcp.alpininsight.ai/"
    assert urls["Documentation"] == "https://insight-ui-webmcp.alpininsight.ai/"
    assert urls["Repository"] == "https://github.com/alpininsight/ais-webmcp"
    assert urls["Issues"] == "https://github.com/alpininsight/ais-webmcp/issues"
    assert urls["Changelog"] == "https://github.com/alpininsight/ais-webmcp/blob/main/CHANGELOG.md"


@pytest.mark.integration
@pytest.mark.parametrize("version", ["0.1.2", "0.1.3"])
def test_normal_installs_and_delivery_inventory(tmp_path, version):
    uv = shutil.which("uv")
    assert uv, "uv is required"
    delivery = tmp_path / "delivery"
    run(
        uv,
        "run",
        "--locked",
        "python",
        "scripts/build_delivery.py",
        "--version",
        version,
        "--output",
        str(delivery),
        cwd=ROOT,
    )
    inventory = json.loads((delivery / "cdn/inventory.json").read_text())
    assert len(inventory["files"]) == 4
    assert inventory["version"] == version
    for entry in inventory["files"]:
        data = (delivery / entry["path"]).read_bytes()
        assert len(data) == entry["size"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    dist = delivery / "dist"
    for wheel in dist.glob("*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            metadata = archive.read(
                next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            ).decode()
            for license_file in ("LICENSE", "NOTICE"):
                member = next(
                    n
                    for n in archive.namelist()
                    if n.endswith(f".dist-info/licenses/{license_file}")
                )
                assert archive.read(member) == (ROOT / license_file).read_bytes()
        # Inspect metadata headers separately from the rendered README body.
        headers = metadata.partition("\n\n")[0].splitlines()
        # PyPI shows a short PEP 639 expression, never the full license text.
        assert "License-Expression: Apache-2.0" in headers
        assert "License-File: LICENSE" in headers
        assert "License-File: NOTICE" in headers
        assert not any(line.startswith("License:") for line in headers)
        assert f"Version: {version}" in headers
    for artifact in [*dist.glob("*.whl"), *dist.glob("*.tar.gz")]:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
                for license_file in ("LICENSE", "NOTICE"):
                    member = next(n for n in names if n.endswith(f"/{license_file}"))
                    stream = archive.extractfile(member)
                    assert stream is not None
                    with stream:
                        assert stream.read() == (ROOT / license_file).read_bytes()
        assert not any(
            name.startswith("docs/")
            or "/docs/" in name
            or "epp-api-changelog" in name
            or "mailbox" in name
            or name.endswith(".mbox")
            or "output/" in name
            for name in names
        )
    for extension in ("whl", "tar.gz"):
        work = tmp_path / extension
        work.mkdir()
        env = isolated_environment()
        venv = work / "venv"
        run(uv, "venv", "--python", sys.executable, str(venv), env=env)
        python = str(venv / "bin/python")
        client = next(dist.glob(f"ais_webmcp-*.{extension}"))
        run(
            uv,
            "pip",
            "install",
            "--python",
            python,
            "--find-links",
            str(dist),
            str(client),
            env=env,
        )
        run(
            python,
            "-c",
            f"import importlib.util, ais_webmcp; assert ais_webmcp.__version__ == '{version}'; assert importlib.util.find_spec('django') is None; assert importlib.util.find_spec('insight_ui') is None",
            cwd=work,
            env=env,
        )
        cli = str(venv / "bin/ais-webmcp")
        manifest = work / "manifest.json"
        run(cli, "init", "--output", str(manifest), cwd=work, env=env)
        run(cli, "validate", str(manifest), cwd=work, env=env)
        run(cli, "doctor", str(manifest), "--format", "json", cwd=work, env=env)
        run(cli, "export", str(manifest), "--output", str(work / "export.yaml"), cwd=work, env=env)
        run(cli, "diff", str(manifest), str(work / "export.yaml"), cwd=work, env=env)
        run(uv, "pip", "check", "--python", python, env=env)
        run(
            python,
            "-c",
            f"from importlib.resources import files; assert 'version:\"{version}\"' in files('ais_webmcp').joinpath('assets/register.js').read_text(); assert files('ais_webmcp').joinpath('fixtures/cross-layer.json').is_file()",
            cwd=work,
            env=env,
        )
