"""Adapter contracts consume this versioned corpus from the installed core."""

from importlib.resources import files
from pathlib import Path


def test_distributed_corpus_matches_js_and_cli_corpus():
    assert (
        files("ais_webmcp").joinpath("fixtures/cross-layer.json").read_bytes()
        == (Path(__file__).parent / "fixtures/cross-layer.json").read_bytes()
    )
