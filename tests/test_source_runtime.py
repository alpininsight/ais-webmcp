"""Source probes must work on General runners without a system Python."""

import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def test_source_probe_bootstraps_runtime_without_system_python(tmp_path):
    """Replay the exit-127 environment without invoking any remote API."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$INVOCATIONS"\n')
    uv.chmod(0o755)
    invocations = tmp_path / "calls"
    step = next(
        step
        for step in workflow()["jobs"]["source"]["steps"]
        if "check_publication.py source" in step.get("run", "")
    )
    result = subprocess.run(
        [shutil.which("bash"), "-e", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": str(bindir),
            "INVOCATIONS": str(invocations),
            "SOURCE_REPOSITORY": "alpininsight/example",
            "SOURCE_SHA": "a" * 40,
            "RELEASE_REQUESTED": "false",
            "CDN_REQUESTED": "false",
            "ENABLED": "",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert invocations.read_text().splitlines() == [
        "run",
        "--no-project",
        "--python",
        "3.14",
        "python",
        "scripts/check_publication.py",
        "source",
        "--repository",
        "alpininsight/example",
        "--sha",
        "a" * 40,
    ]


def test_each_validator_job_owns_its_runtime_without_dependency_sync():
    jobs = workflow()["jobs"]
    checked = set()
    for name, job in jobs.items():
        steps = job.get("steps", [])
        probes = [i for i, s in enumerate(steps) if "check_publication.py" in s.get("run", "")]
        if not probes:
            continue
        checked.add(name)
        setup = [
            i for i, s in enumerate(steps) if s.get("uses", "").startswith("astral-sh/setup-uv@")
        ]
        assert len(setup) == 1 and setup[0] < min(probes), name
        config = steps[setup[0]]
        assert config["uses"] == "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7"
        assert config["with"] == {"python-version": "3.14", "enable-cache": False}
        assert "if" not in config
        for index in probes:
            run = steps[index]["run"]
            assert "uv run --no-project --python 3.14 python scripts/check_publication.py" in run
            assert "python3 scripts/check_publication.py" not in run
            assert "uv sync" not in run and "pytest" not in run and "pip install" not in run
    assert checked == ({"source", "pypi-verified", "cdn-verified"} if "cdn" in jobs else {"source"})
