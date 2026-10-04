"""Shared WebMCP manifest schema, dataclasses, profiles, and validator.

Shipped inside the ``ais-webmcp`` distribution (not a third PyPI package).
Django hosts import this module from ``insight-ui-webmcp``, which depends on
``ais-webmcp``. This package does not import Django.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.0.0"
