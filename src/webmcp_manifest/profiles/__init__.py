"""Built-in WebMCP host profiles."""

from __future__ import annotations

from webmcp_manifest.profiles.base import Profile, get_profile, list_profiles
from webmcp_manifest.profiles.webpage import WebpageProfile  # noqa: F401 — registers

__all__ = [
    "Profile",
    "WebpageProfile",
    "get_profile",
    "list_profiles",
]
