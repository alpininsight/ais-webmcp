"""Dataclasses describing WebMCP tool specifications and manifests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One registrable WebMCP tool.

    Attributes:
        id: Stable tool identifier exposed to agents.
        name: Human-readable tool name.
        description: Short capability description.
        consequential: When True, the tool may have side effects (e.g. subscribe).
        parameters: Optional JSON-schema-like parameter object.
        input_schema: Alias-friendly schema dict written into the manifest.
    """

    id: str
    name: str
    description: str
    consequential: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        payload = asdict(self)
        # Prefer a single schema key in the written manifest.
        schema = payload.pop("input_schema") or payload.pop("parameters") or {}
        payload.pop("parameters", None)
        if schema:
            payload["inputSchema"] = schema
        return payload


@dataclass(frozen=True, slots=True)
class WebmcpManifest:
    """Host-facing WebMCP manifest written by ``webmcp_prepare``."""

    profile: str
    version: str
    tools: tuple[ToolSpec, ...]
    anchors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "profile": self.profile,
            "version": self.version,
            "anchors": list(self.anchors),
            "tools": [tool.to_dict() for tool in self.tools],
            "notes": list(self.notes),
        }
