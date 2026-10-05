"""Webpage profile: company one-pager section anchors and WebMCP tool ids."""

from __future__ import annotations

from ais_webmcp.manifest import ToolSpec, WebmcpManifest
from ais_webmcp.profiles.base import register_profile

# Section anchors used on Insight UI company / marketing one-pagers.
WEBPAGE_ANCHORS: tuple[str, ...] = (
    "problem",
    "integration",
    "semantics",
    "trust",
    "platform",
    "products",
    "open-source",
    "architecture",
    "contact",
)


class WebpageProfile:
    """Profile for webpage-style Insight UI hosts (marketing / company sites)."""

    name = "webpage"

    def describe_anchors(self) -> tuple[str, ...]:
        """Return the canonical one-pager section anchors."""
        return WEBPAGE_ANCHORS

    def describe_tools(self) -> tuple[ToolSpec, ...]:
        """Return tools for section navigation, pitch, contact, and conversation."""
        section_param = {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section anchor id",
                    "enum": list(WEBPAGE_ANCHORS),
                }
            },
            "required": ["section"],
        }
        return (
            ToolSpec(
                id="list_sections",
                group="navigation",
                read_only=True,
                name="List sections",
                description="List available page section anchors on this host.",
            ),
            ToolSpec(
                id="go_to_section",
                group="navigation",
                name="Go to section",
                description="Scroll or navigate the page to a named section anchor.",
                input_schema=section_param,
            ),
            ToolSpec(
                id="get_section",
                group="content",
                read_only=True,
                name="Get section",
                description="Return the text content of a named section.",
                input_schema=section_param,
            ),
            ToolSpec(
                id="get_company_pitch",
                group="content",
                read_only=True,
                name="Get company pitch",
                description="Return a short company / product pitch summary.",
            ),
            ToolSpec(
                id="get_contact",
                group="legal_contact",
                read_only=True,
                name="Get contact",
                description="Return public contact details for this host.",
            ),
            ToolSpec(
                id="open_legal",
                group="legal_contact",
                name="Open legal",
                description="Open imprint, privacy, or other legal pages.",
            ),
            ToolSpec(
                id="subscribe_newsletter",
                group="consequential",
                name="Subscribe newsletter",
                description="Subscribe an email address to the host newsletter.",
                consequential=True,
                input_schema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "format": "email",
                            "description": "Subscriber email address",
                        }
                    },
                    "required": ["email"],
                },
            ),
            ToolSpec(
                id="start_conversation",
                group="legal_contact",
                name="Start conversation",
                description="Start an assisted conversation about this host's content.",
            ),
        )

    def build_manifest(self, *, version: str = "1") -> WebmcpManifest:
        """Build the webpage WebMCP manifest."""
        return WebmcpManifest(
            profile=self.name,
            version=version,
            tools=self.describe_tools(),
            anchors=self.describe_anchors(),
            notes=(
                "Hosts should commit webmcp.manifest.json next to the site root "
                "or document its deploy path.",
                "Include {% load webmcp_tags %}{% webmcp_assets %} in base.html.",
                "subscribe_newsletter is consequential and ships enabled false; "
                "do not opt in by default.",
            ),
        )


register_profile(WebpageProfile())
