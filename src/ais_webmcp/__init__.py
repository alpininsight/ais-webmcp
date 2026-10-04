"""Django-free Dev/CI client for WebMCP manifests.

The console script is ``ais-webmcp``. Shared schema and validation live in
``webmcp_manifest``, which this distribution also ships. Neither import loads
Django.
"""

from __future__ import annotations

__version__ = "0.0.0"

__all__ = ["__version__"]
