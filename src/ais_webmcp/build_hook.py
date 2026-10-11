"""Stamp bundled runtime assets from wheel metadata, never a second version source."""

import re
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return
        version = self.metadata.version
        root = Path(self.root)
        client = root / "src/ais_webmcp"
        source = client / "assets/register.js"
        self.temporary = tempfile.TemporaryDirectory(prefix="ais-webmcp-wheel-")
        target = Path(self.temporary.name) / "register.js"
        text = source.read_text(encoding="utf-8")
        pattern = r'(version\s*:\s*)"0\.0\.0"'
        if len(re.findall(pattern, text)) != 1:
            raise ValueError("runtime version marker must appear exactly once")
        target.write_text(
            re.sub(pattern, lambda match: match[1] + f'"{version}"', text), encoding="utf-8"
        )
        relative = "ais_webmcp/assets/register.js"
        build_data.setdefault("force_include", {})[str(target)] = relative

    def finalize(self, version, build_data, artifact_path):
        if hasattr(self, "temporary"):
            self.temporary.cleanup()
