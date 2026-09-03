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

import aiohttp
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
    def __init__(self, json_data=None, headers=None, status=200, raise_exc=None):
        self._json_data = json_data
        self.headers = headers or {}
        self.status = status
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

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


class SequencedSession:
    """Like FakeSession but each URL maps to a *queue* of outcomes, consumed
    one per get() call - so a URL can fail transiently on the first attempt(s)
    and then succeed. Queue entries are FakeResponse instances (a
    FakeResponse with raise_exc set models a transient error)."""

    def __init__(self, sequences: dict[str, list]):
        self._seq = {url: list(items) for url, items in sequences.items()}
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}})
        queue = self._seq.get(url)
        if not queue:
            raise AssertionError(f"unexpected request to {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Never actually sleep between retries - record the backoff delays instead."""
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(update_versions.asyncio, "sleep", fake_sleep)
    return slept


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


def transient():
    """A response whose raise_for_status() raises a retryable error."""
    return FakeResponse(raise_exc=aiohttp.ClientError("connection reset"))


class TestGetJsonWithRetry:
    """The shared retry/backoff helper behind list_{dockerhub,ghcr,quay}_tags.
    The retry path had no coverage when it was extracted from the individual
    functions - only the happy path did."""

    URL = "https://example.test/v2/repo/tags/list"

    @pytest.mark.asyncio
    async def test_returns_first_success_without_sleeping(self, _no_sleep):
        session = SequencedSession({self.URL: [FakeResponse({"tags": ["1.0.0"]})]})

        data, headers = await update_versions._get_json_with_retry(session, self.URL, {}, "test")

        assert data == {"tags": ["1.0.0"]}
        assert _no_sleep == []
        assert len(session.calls) == 1

    @pytest.mark.asyncio
    async def test_recovers_after_transient_errors(self, _no_sleep):
        session = SequencedSession({self.URL: [transient(), transient(), FakeResponse({"tags": ["1.0.0"]})]})

        data, _ = await update_versions._get_json_with_retry(session, self.URL, {}, "test")

        assert data == {"tags": ["1.0.0"]}
        assert len(session.calls) == 3
        assert _no_sleep == [1, 2]  # exponential backoff: 2**0, 2**1

    @pytest.mark.asyncio
    async def test_raises_after_exhausting_retries(self, _no_sleep):
        session = SequencedSession({self.URL: [transient(), transient(), transient()]})

        with pytest.raises(aiohttp.ClientError):
            await update_versions._get_json_with_retry(session, self.URL, {}, "test")

        assert len(session.calls) == 3  # max_retries, not more
        assert _no_sleep == [1, 2]  # slept between attempts, not after the last

    @pytest.mark.asyncio
    async def test_max_retries_is_configurable(self, _no_sleep):
        session = SequencedSession({self.URL: [transient()] * 5})

        with pytest.raises(aiohttp.ClientError):
            await update_versions._get_json_with_retry(session, self.URL, {}, "test", max_retries=5)

        assert len(session.calls) == 5
        assert _no_sleep == [1, 2, 4, 8]


class TestListGhcrTagsRetry:
    @pytest.mark.asyncio
    async def test_transient_error_on_tags_page_recovers(self, _no_sleep):
        token_url = "https://ghcr.io/token?service=ghcr.io&scope=repository:owner/repo:pull"
        tags_url = "https://ghcr.io/v2/owner/repo/tags/list?n=1000"
        session = SequencedSession(
            {
                token_url: [FakeResponse({"token": "t"})],
                tags_url: [transient(), FakeResponse({"tags": ["1.0.0", "2.0.0"]})],
            }
        )

        tags = await update_versions.list_ghcr_tags(session, "owner/repo")

        assert tags == ["1.0.0", "2.0.0"]
        assert _no_sleep == [1]


class TestListGcrTags:
    """list_gcr_tags keeps its own retry loop (it has a pre-raise_for_status
    401 check the shared helper doesn't) - so it needs its own coverage."""

    URL = "https://gcr.io/v2/owner/repo/tags/list"

    @pytest.mark.asyncio
    async def test_401_returns_empty_without_retrying(self, _no_sleep):
        session = SequencedSession({self.URL: [FakeResponse(status=401)]})

        tags = await update_versions.list_gcr_tags(session, "owner/repo")

        assert tags == []
        assert len(session.calls) == 1  # no retry on a 401
        assert _no_sleep == []

    @pytest.mark.asyncio
    async def test_retries_transient_then_succeeds(self, _no_sleep):
        session = SequencedSession({self.URL: [transient(), FakeResponse({"tags": ["1.0.0"]})]})

        tags = await update_versions.list_gcr_tags(session, "owner/repo")

        assert tags == ["1.0.0"]
        assert _no_sleep == [1]

    @pytest.mark.asyncio
    async def test_gives_up_after_retries_and_returns_empty(self, _no_sleep):
        session = SequencedSession({self.URL: [transient(), transient(), transient()]})

        tags = await update_versions.list_gcr_tags(session, "owner/repo")

        assert tags == []  # outer except swallows the final raise
        assert _no_sleep == [1, 2]
