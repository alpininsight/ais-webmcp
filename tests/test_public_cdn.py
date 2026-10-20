"""The public edge must serve the complete release, not just valid headers."""

import importlib.util
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication", ROOT / "scripts/check_publication.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


@pytest.fixture
def bundle(tmp_path):
    cdn = tmp_path / "cdn"
    cdn.mkdir()
    (cdn / "register.js").write_bytes(b"release runtime")
    (cdn / "webmcp-manifest.schema.json").write_bytes(b'{"type":"object"}')
    (cdn / "inventory.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "cdn_prefix": "ais-webmcp",
                "files": [
                    {"path": f"cdn/{name}"}
                    for name in ("register.js", "webmcp-manifest.schema.json")
                ],
            }
        )
    )
    return tmp_path


class Response(io.BytesIO):
    def __init__(self, request, bundle, defect=None):
        name = request.full_url.rsplit("/", 1)[1]
        data = (bundle / "cdn" / name).read_bytes()
        super().__init__(b"wrong" if defect == "bytes" else data)
        self.status = 206 if defect == "partial" else 200
        self.url = request.full_url + "/login" if defect == "redirect" else request.full_url
        self.headers = Message()
        self.headers["Content-Type"] = (
            "text/html"
            if defect == "mime"
            else "text/javascript; charset=utf-8"
            if name.endswith(".js")
            else "application/json"
        )
        immutable = "/v0.1.0/" in request.full_url
        self.headers["Cache-Control"] = (
            "private, max-age=300"
            if defect == "private"
            else "public, max-age=300, max-age=31536000"
            if defect == "duplicate"
            else "public, max-age=31536000, immutable"
            if immutable
            else "public, max-age=300"
        )
        if defect != "cors":
            self.headers["Access-Control-Allow-Origin"] = "*"

    def geturl(self):
        return self.url


def test_every_object_and_alias_is_read_in_full(bundle, monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        return Response(request, bundle)

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    report = publication.verify_cdn(bundle, "0.1.0")
    assert len(report) == len(requests) == 9
    assert {x["url"].split("/")[-2] for x in report} == {"v0.1.0", "main", "latest"}
    assert {x["url"].split("/")[-1] for x in report} == {
        "register.js",
        "webmcp-manifest.schema.json",
        "inventory.json",
    }
    assert all(request.get_method() == "GET" for request in requests)
    assert all(
        request.get_header("User-agent") == "AlpinInsight-WebMCP-PublicationVerifier/1.0"
        and request.get_header("Accept") == "*/*"
        and request.get_header("Origin") == "https://insight-ui.com"
        and not request.has_header("Cookie")
        and not request.has_header("Authorization")
        for request in requests
    )
    assert all(
        not request.has_header("Range") and "?" not in request.full_url for request in requests
    )
    assert all(len(x["sha256"]) == 64 and x["size"] > 0 for x in report)


@pytest.mark.parametrize(
    "defect", ["bytes", "partial", "redirect", "mime", "private", "duplicate", "cors"]
)
def test_edge_defects_cannot_pass(bundle, monkeypatch, defect):
    monkeypatch.setattr(
        publication.urllib.request,
        "urlopen",
        lambda request, timeout: Response(request, bundle, defect),
    )
    with pytest.raises(ValueError, match="CDN"):
        publication.verify_cdn(bundle, "0.1.0")


def test_edge_challenge_is_not_bypassed(bundle, monkeypatch):
    def challenged(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(publication.urllib.request, "urlopen", challenged)
    with pytest.raises(urllib.error.HTTPError):
        publication.verify_cdn(bundle, "0.1.0")


@pytest.mark.parametrize("version", ["0.0.0", "latest", "v0.1.0", "0.1.0.dev1", "01.0.0"])
def test_invalid_pin_is_rejected_before_network(bundle, monkeypatch, version):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid pin must never reach the network")

    monkeypatch.setattr(publication.urllib.request, "urlopen", forbidden)
    with pytest.raises(ValueError, match="release version"):
        publication.verify_cdn(bundle, version)


@pytest.mark.parametrize(
    "values", [["*", "*"], ["*", "https://insight-ui.com"], ["*, https://insight-ui.com"]]
)
def test_multiple_cors_values_are_rejected(bundle, monkeypatch, values):
    def urlopen(request, timeout):
        response = Response(request, bundle)
        del response.headers["Access-Control-Allow-Origin"]
        for value in values:
            response.headers["Access-Control-Allow-Origin"] = value
        return response

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError, match="CORS"):
        publication.verify_cdn(bundle, "0.1.0")


@pytest.fixture
def clock(monkeypatch):
    elapsed = [0]
    sleeps = []

    def sleep(seconds):
        elapsed[0] += seconds
        sleeps.append(seconds)

    monkeypatch.setattr(publication.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(publication.time, "sleep", sleep)
    return elapsed, sleeps


def test_mutable_aliases_converge_after_entire_ttl(bundle, monkeypatch, clock):
    elapsed, sleeps = clock
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        stale = "/v0.1.0/" not in request.full_url and elapsed[0] < 320
        return Response(request, bundle, "bytes" if stale else None)

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    report = publication.verify_cdn(bundle, "0.1.0")
    assert len(report) == 9
    assert sum(sleeps) == 320  # A one-minute retry budget would fail this release.
    assert all(
        "?" not in request.full_url and not request.has_header("Cache-Control")
        for request in requests
    )


def test_mutable_mismatch_has_one_bounded_deadline(bundle, monkeypatch, clock):
    elapsed, sleeps = clock
    monkeypatch.setattr(
        publication.urllib.request,
        "urlopen",
        lambda request, timeout: Response(
            request, bundle, "bytes" if "/main/" in request.full_url else None
        ),
    )
    with pytest.raises(ValueError, match="bytes"):
        publication.verify_cdn(bundle, "0.1.0")
    assert elapsed[0] == sum(sleeps) == 360


def test_mutable_challenge_fails_without_retry_or_bypass(bundle, monkeypatch, clock):
    def urlopen(request, timeout):
        if "/main/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        return Response(request, bundle)

    monkeypatch.setattr(publication.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        publication.verify_cdn(bundle, "0.1.0")
    assert clock[1] == []
