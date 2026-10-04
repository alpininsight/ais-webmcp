"""Profile protocol and registry for WebMCP host flavours."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from webmcp_manifest.manifest import ToolSpec, WebmcpManifest

_REGISTRY: dict[str, Profile] = {}


@runtime_checkable
class Profile(Protocol):
    """Host profile that describes tools and optional section anchors."""

    name: str

    def describe_tools(self) -> tuple[ToolSpec, ...]:
        """Return the tools this profile exposes."""
        ...

    def describe_anchors(self) -> tuple[str, ...]:
        """Return optional page section anchors (webpage-style hosts)."""
        ...

    def build_manifest(self, *, version: str = "1") -> WebmcpManifest:
        """Build a host-facing manifest for prepare/status commands."""
        ...


def register_profile(profile: Profile) -> Profile:
    """Register a profile instance under ``profile.name``."""
    _REGISTRY[profile.name] = profile
    return profile


def get_profile(name: str) -> Profile:
    """Look up a registered profile by name."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown WebMCP profile {name!r}. Known: {known}") from exc


def list_profiles() -> tuple[str, ...]:
    """Return sorted registered profile names."""
    return tuple(sorted(_REGISTRY))
