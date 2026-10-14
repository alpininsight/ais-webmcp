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
        output_schema: JSON Schema for the tool result. ``None`` omits
            ``outputSchema``. Validation still succeeds and reports a
            low-severity ``missing_output_schema`` finding. Pass a dict,
            including ``{}``, to declare a schema. Prefer one for every tool
            that returns structured data.
        read_only: Maps to ``annotations.readOnlyHint`` for non-consequential tools.
        debugging: Marks the tool itself as DevTools/inspection-only (issue #9).
            Written only when ``to_dict(include_debugging=True)``; never inferred
            from Django ``DEBUG`` or ``window.JS_DEBUG``.
        group: Optional molecule name for Atomic Design listing (#20).
        untrusted_content: Tool output carries data from external or
            unverified sources (WebMCP ``annotations.untrustedContentHint``,
            Chrome 149+). Emitted only when True; first-party page content
            stays unmarked.
    """

    id: str
    name: str
    description: str
    consequential: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    read_only: bool = False
    debugging: bool = False
    group: str | None = None
    untrusted_content: bool = False

    def to_dict(self, *, include_debugging: bool = False) -> dict[str, Any]:
        """Serialize to a manifest object that satisfies the shared schema.

        Empty parameter specs become an object schema so validate and prepare
        cannot drift. Consequential tools are written ``enabled: false`` —
        newsletter and other side effects stay off unless a host edits the
        file (issue #3). This dataclass cannot opt a tool in.

        ``annotations.debugging`` is emitted only when the tool is marked
        ``debugging=True`` **and** ``include_debugging=True`` (explicit prepare
        flag). Django ``DEBUG`` alone never reaches this method.
        """
        payload = asdict(self)
        payload.pop("read_only")
        debugging = payload.pop("debugging")
        group = payload.pop("group")
        untrusted_content = payload.pop("untrusted_content")
        output_schema = payload.pop("output_schema")
        schema = (
            payload.pop("input_schema")
            or payload.pop("parameters")
            or {
                "type": "object",
                "properties": {},
            }
        )
        payload.pop("parameters", None)
        payload["inputSchema"] = schema
        if output_schema is not None:
            payload["outputSchema"] = output_schema
        if self.consequential:
            annotations: dict[str, Any] = {"readOnlyHint": False, "consequentialHint": True}
            payload["enabled"] = False
        else:
            annotations = {"readOnlyHint": self.read_only}
        if untrusted_content:
            annotations["untrustedContentHint"] = True
        if debugging and include_debugging:
            annotations["debugging"] = True
        payload["annotations"] = annotations
        if isinstance(group, str) and group.strip():
            payload["group"] = group.strip()
        return payload


@dataclass(frozen=True, slots=True)
class WebmcpManifest:
    """Host-facing WebMCP manifest written by ``webmcp_prepare``."""

    profile: str
    version: str
    tools: tuple[ToolSpec, ...]
    anchors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self, *, include_debugging: bool = False) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict.

        ``include_debugging`` is the sole prepare opt-in for
        ``annotations.debugging`` (issue #9). It is never derived from Django
        ``DEBUG`` or host ``JS_DEBUG``.
        """
        return {
            "profile": self.profile,
            "version": self.version,
            "anchors": list(self.anchors),
            "tools": [tool.to_dict(include_debugging=include_debugging) for tool in self.tools],
            "notes": list(self.notes),
        }
