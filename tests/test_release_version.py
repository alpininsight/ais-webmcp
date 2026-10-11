"""0.0.0, checkout/dev and non-GitVersion strings never become a delivery."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("delivery", ROOT / "scripts/build_delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


@pytest.mark.parametrize(
    "version",
    [
        "0.0.0",
        "0.1.0.dev0",
        "0.1.0-alpha.53",
        "0.1.0a1",
        "0.1.0b1",
        "0.1.0rc1",
        "0.1.0.post1",
        "0.1.0+local",
        "v0.1.0",
        "01.0.0",
        "0.1",
        "",
    ],
)
def test_build_refuses_non_release_versions(tmp_path, monkeypatch, version):
    def forbidden(*args, **kwargs):
        raise AssertionError("version must be rejected before any build step")

    monkeypatch.setattr(delivery.subprocess, "run", forbidden)
    monkeypatch.setattr(delivery.subprocess, "check_output", forbidden)
    with pytest.raises(ValueError, match="nonzero GitVersion version"):
        delivery.build(version, tmp_path / "out")


def test_source_runtime_marker_stays_a_build_placeholder():
    """The committed JS keeps exactly one 0.0.0 marker that the wheel hook stamps."""
    source = (ROOT / "src/ais_webmcp/assets/register.js").read_text()
    assert len(re.findall(r'version\s*:\s*"0\.0\.0"', source)) == 1


@pytest.mark.parametrize("version", ["0.1.0", "0.1.1", "1.0.0", "10.20.30"])
def test_build_accepts_final_release_versions(tmp_path, monkeypatch, version):
    """A final GitVersion MajorMinorPatch passes the guard and reaches the build."""

    class Reached(Exception):
        pass

    def reached(*args, **kwargs):
        raise Reached

    monkeypatch.setattr(delivery.subprocess, "check_output", reached)
    with pytest.raises(Reached):
        delivery.build(version, tmp_path / "out")
