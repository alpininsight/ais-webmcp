"""Unit tests for WebMCP profiles (no insight-ui import required)."""

from __future__ import annotations

import json

import pytest

from insight_ui_webmcp.manifest import ToolSpec, WebmcpManifest
from insight_ui_webmcp.profiles import get_profile, list_profiles
from insight_ui_webmcp.profiles.webpage import WEBPAGE_ANCHORS, WebpageProfile


@pytest.mark.unit
def test_webpage_profile_registered() -> None:
    assert "webpage" in list_profiles()
    profile = get_profile("webpage")
    assert profile.name == "webpage"


@pytest.mark.unit
def test_webpage_anchors() -> None:
    profile = WebpageProfile()
    anchors = profile.describe_anchors()
    assert anchors == WEBPAGE_ANCHORS
    for expected in (
        "problem",
        "integration",
        "semantics",
        "trust",
        "platform",
        "products",
        "open-source",
        "architecture",
        "contact",
    ):
        assert expected in anchors


@pytest.mark.unit
def test_webpage_tool_ids() -> None:
    tools = WebpageProfile().describe_tools()
    ids = {tool.id for tool in tools}
    assert ids == {
        "list_sections",
        "go_to_section",
        "get_section",
        "get_company_pitch",
        "get_contact",
        "open_legal",
        "subscribe_newsletter",
        "start_conversation",
    }
    subscribe = next(t for t in tools if t.id == "subscribe_newsletter")
    assert subscribe.consequential is True
    serialized = next(
        tool
        for tool in WebpageProfile().build_manifest().to_dict()["tools"]
        if tool["id"] == "subscribe_newsletter"
    )
    assert serialized["enabled"] is False
    assert serialized["annotations"]["consequentialHint"] is True
    assert serialized["annotations"]["readOnlyHint"] is False


@pytest.mark.unit
def test_manifest_serializes() -> None:
    manifest = WebpageProfile().build_manifest(version="1")
    assert isinstance(manifest, WebmcpManifest)
    payload = manifest.to_dict()
    # Round-trip through JSON to ensure host file is valid.
    dumped = json.loads(json.dumps(payload))
    assert dumped["profile"] == "webpage"
    assert len(dumped["tools"]) == 8
    assert "list_sections" in {t["id"] for t in dumped["tools"]}


@pytest.mark.unit
def test_tool_spec_to_dict_uses_input_schema() -> None:
    spec = ToolSpec(
        id="go_to_section",
        name="Go to section",
        description="Navigate",
        input_schema={"type": "object"},
    )
    data = spec.to_dict()
    assert data["id"] == "go_to_section"
    assert data["inputSchema"] == {"type": "object"}
    assert "parameters" not in data


@pytest.mark.unit
def test_unknown_profile_raises() -> None:
    with pytest.raises(KeyError, match="Unknown WebMCP profile"):
        get_profile("does-not-exist")
