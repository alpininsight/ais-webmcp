"""``python -m ais_webmcp`` entry. Does not import Django."""

from __future__ import annotations

from ais_webmcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
