"""
Tests for the registry-fetching network code (list_ghcr_tags) using a
hand-rolled fake aiohttp session rather than a third-party mocking library.

aioresponses (the standard aiohttp-mocking library) was tried first and
rejected: even its latest release (0.7.9) raises
"ClientResponse.__init__() missing 1 required keyword-only argument:
'stream_writer'" against the aiohttp version this action currently
installs (aiohttp>=3.9.0 resolves to 3.14.x) - it hooks aiohttp's
internals rather than its public API, and hasn't caught up. A fake
session/response implementing just the .get()/.json()/.headers surface
these functions actually call avoids that fragility entirely.

Before this file, none of the functions that actually talk to a registry
over HTTP had any test coverage at all - every other test file exercises
only pure string/dict/regex logic. This repo's own CHANGELOG documents
fixing two real bugs in exactly this code (a ghcr.io pagination loop that
re-fetched the same page forever, and a deprecated aiohttp.BasicAuth
usage) with nothing in CI that would have caught either one.
"""

import base64
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest


def load_update_versions():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "update-versions.py"
    loader = SourceFileLoader("update_versions", str(script_path))
    spec = spec_from_loader("update_versions", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


update_versions = load_update_versions()


class FakeResponse:
    def __init__(self, json_data, headers=None):
        self._json_data = json_data
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """Maps a URL to a canned FakeResponse. Records every call for
    assertions (e.g. checking the Authorization header actually sent)."""

    def __init__(self, responses: dict[str, FakeResponse]):
        self._responses = responses
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}})
        if url not in self._responses:
            raise AssertionError(f"unexpected request to {url}")
        return self._responses[url]


class TestListGhcrTags:
    """Tests for list_ghcr_tags - the exact function whose pagination bug
    is documented in this repo's own CHANGELOG."""

    @pytest.mark.asyncio
    async def test_single_page_terminates_without_looping(self):
        """A repo whose tags fit on one page (no Link header at all) must
        return those tags and stop - not re-fetch the same page forever.
        This is the specific historical bug: `url` was only reset to None
        when a next-page Link header was present; missing that reset for
        the no-more-pages case looped indefinitely for exactly this input
        shape."""
        token_url = "https://ghcr.io/token?service=ghcr.io&scope=repository:owner/repo:pull"
        tags_url = "https://ghcr.io/v2/owner/repo/tags/list?n=1000"
        session = FakeSession(
            {
                token_url: FakeResponse({"token": "fake-bearer-token"}),
                tags_url: FakeResponse({"tags": ["1.0.0", "1.1.0"]}),  # no Link header - single page
            }
        )

        tags = await update_versions.list_ghcr_tags(session, "owner/repo")

        assert tags == ["1.0.0", "1.1.0"]
        # Confirm it didn't loop: exactly one request to the tags endpoint.
        tag_requests = [c for c in session.calls if c["url"] == tags_url]
        assert len(tag_requests) == 1

    @pytest.mark.asyncio
    async def test_multi_page_follows_link_header_and_terminates(self):
        """A paginated response (Link: rel="next") must fetch every page
        and aggregate all tags, then stop once a page has no next link."""
        token_url = "https://ghcr.io/token?service=ghcr.io&scope=repository:owner/repo:pull"
        page1_url = "https://ghcr.io/v2/owner/repo/tags/list?n=1000"
        page2_url = "https://ghcr.io/v2/owner/repo/tags/list?n=1000&last=1.0.0"
        session = FakeSession(
            {
                token_url: FakeResponse({"token": "fake-bearer-token"}),
                page1_url: FakeResponse(
                    {"tags": ["1.0.0"]},
                    headers={"Link": '</v2/owner/repo/tags/list?n=1000&last=1.0.0>; rel="next"'},
                ),
                page2_url: FakeResponse({"tags": ["1.1.0"]}),  # last page - no Link header
            }
        )

        tags = await update_versions.list_ghcr_tags(session, "owner/repo")

        assert tags == ["1.0.0", "1.1.0"]
        assert len([c for c in session.calls if c["url"] == page1_url]) == 1
        assert len([c for c in session.calls if c["url"] == page2_url]) == 1

    @pytest.mark.asyncio
    async def test_token_exchange_uses_encode_basic_auth_not_deprecated_basicauth(self, monkeypatch):
        """Guards against silently regressing back to the deprecated
        aiohttp.BasicAuth + auth= kwarg this repo already had to migrate
        away from (see CHANGELOG) - asserts the actual Authorization
        header sent for the token exchange is a correctly-formed Basic
        auth header for ("token", <GITHUB_TOKEN>)."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_faketoken123")
        expected = "Basic " + base64.b64encode(b"token:ghp_faketoken123").decode()

        token_url = "https://ghcr.io/token?service=ghcr.io&scope=repository:owner/repo:pull"
        tags_url = "https://ghcr.io/v2/owner/repo/tags/list?n=1000"
        session = FakeSession(
            {
                token_url: FakeResponse({"token": "fake-bearer-token"}),
                tags_url: FakeResponse({"tags": []}),
            }
        )

        await update_versions.list_ghcr_tags(session, "owner/repo")

        token_call = next(c for c in session.calls if c["url"] == token_url)
        assert token_call["headers"]["Authorization"] == expected
