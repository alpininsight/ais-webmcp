"""Read-only tool listing for a WebMCP manifest. Does not import Django.

Prints name, description, enabled, and an annotations summary. Does not
register tools and does not read a live page. Invalid manifests are not
listed; the caller gets the same exit codes as ``validate``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webmcp_manifest.validate import (
    ValidationResult,
    exit_code,
    load_manifest,
    render,
    validate_data,
)

_ANNOTATION_KEYS = ("readOnlyHint", "consequentialHint", "untrustedContentHint")


@dataclass(frozen=True, slots=True)
class ListedTool:
    """One tool row. ``enabled`` is None when the manifest omits the key."""

    id: str | None
    name: str
    description: str
    enabled: bool | None
    annotations: tuple[tuple[str, bool], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "annotations": dict(self.annotations),
        }


@dataclass(frozen=True, slots=True)
class ManifestListing:
    """Tools from one valid manifest."""

    source: str
    profile: str
    version: str
    tools: tuple[ListedTool, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.source,
            "profile": self.profile,
            "version": self.version,
            "tools": [tool.to_dict() for tool in self.tools],
        }


def _listed_tool(tool: dict[str, Any]) -> ListedTool:
    raw_id = tool.get("id")
    raw_name = tool.get("name")
    raw_description = tool.get("description")
    annotations = tool.get("annotations")
    pairs: list[tuple[str, bool]] = []
    if isinstance(annotations, dict):
        for key in _ANNOTATION_KEYS:
            value = annotations.get(key)
            if isinstance(value, bool):
                pairs.append((key, value))
    enabled: bool | None
    if "enabled" not in tool:
        enabled = None
    else:
        value = tool.get("enabled")
        enabled = value if isinstance(value, bool) else None
    return ListedTool(
        id=raw_id if isinstance(raw_id, str) else None,
        name=raw_name if isinstance(raw_name, str) else "",
        description=raw_description if isinstance(raw_description, str) else "",
        enabled=enabled,
        annotations=tuple(pairs),
    )


def list_path(
    path: Path | str,
    *,
    extra_profiles: tuple[str, ...] | list[str] = (),
) -> ManifestListing | ValidationResult:
    """List tools in ``path``, or return a failed validation result."""
    data, fatal = load_manifest(path)
    if fatal is not None:
        return fatal
    checked = validate_data(data, source=str(Path(path)), extra_profiles=extra_profiles)
    if not checked.ok:
        return checked
    if not isinstance(data, dict):
        return checked
    tools = data.get("tools")
    rows = tuple(_listed_tool(tool) for tool in tools if isinstance(tool, dict))
    profile = data.get("profile")
    version = data.get("version")
    return ManifestListing(
        source=str(Path(path)),
        profile=profile if isinstance(profile, str) else "",
        version=version if isinstance(version, str) else "",
        tools=rows,
    )


def _enabled_text(enabled: bool | None) -> str:
    if enabled is None:
        return "(omitted)"
    return "true" if enabled else "false"


def _annotations_text(annotations: tuple[tuple[str, bool], ...]) -> str:
    if not annotations:
        return "(none)"
    return ", ".join(f"{key}={'true' if value else 'false'}" for key, value in annotations)


def _heading(tool: ListedTool) -> str:
    if tool.id:
        return tool.id
    return tool.name or "(unnamed)"


def render_text(listings: list[ManifestListing]) -> str:
    """Human-readable tool list. One block per manifest."""
    blocks: list[str] = []
    for listing in listings:
        lines = [
            f"{listing.source}  profile={listing.profile}  version={listing.version}  "
            f"tools={len(listing.tools)}"
        ]
        for tool in listing.tools:
            lines.append(_heading(tool))
            lines.append(f"  name: {tool.name}")
            lines.append(f"  description: {tool.description}")
            lines.append(f"  enabled: {_enabled_text(tool.enabled)}")
            lines.append(f"  annotations: {_annotations_text(tool.annotations)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_json(listings: list[ManifestListing]) -> str:
    """Machine-readable tool list. One JSON document, or an array of them."""
    payload: Any
    if len(listings) == 1:
        payload = listings[0].to_dict()
    else:
        payload = [listing.to_dict() for listing in listings]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_listings(listings: list[ManifestListing], fmt: str) -> str:
    """Render listings as ``text`` or ``json``."""
    if fmt == "json":
        return render_json(listings)
    if fmt == "text":
        return render_text(listings)
    raise ValueError(f"unknown format {fmt!r}")


def list_manifests(
    paths: list[Path],
    *,
    fmt: str,
    extra_profiles: tuple[str, ...] | list[str] = (),
) -> tuple[str, int]:
    """List every path. On any failure, render validation output and do not list."""
    outcomes = [list_path(path, extra_profiles=extra_profiles) for path in paths]
    failures = [item for item in outcomes if isinstance(item, ValidationResult)]
    if failures:
        # Keep validate's report shape so a bad manifest is not half-listed.
        results = [
            item if isinstance(item, ValidationResult) else _ok_placeholder(item)
            for item in outcomes
        ]
        return render(results, fmt), exit_code(results)
    listings = [item for item in outcomes if isinstance(item, ManifestListing)]
    return render_listings(listings, fmt), 0


def _ok_placeholder(listing: ManifestListing) -> ValidationResult:
    """Validation-shaped success used only when a batch mixes ok and failed files."""
    return ValidationResult(ok=True, source=listing.source, issues=())
