"""CSS rewriting in the browser proxy: @import and text/css responses."""
from __future__ import annotations

from unittest.mock import patch
from urllib.parse import quote

import pytest
import respx
from httpx import Response

from tinyagentos.routes.desktop_browser.rewriter import rewrite_html


def _proxy(url: str) -> str:
    return f"/api/desktop/browser/proxy?profile_id=p&url={quote(url, safe='')}"


def test_import_string_in_style_block_is_rewritten():
    html = b'<html><head><style>@import "https://evil.example/x.css"; a{color:red}</style></head></html>'
    out = rewrite_html(html, base_url="https://example.com/", proxy=_proxy)
    assert b"/api/desktop/browser/proxy?profile_id=p&url=https%3A%2F%2Fevil.example%2Fx.css" in out
    assert b'"https://evil.example/x.css"' not in out


def test_import_url_form_in_style_block_is_rewritten():
    html = b"<html><head><style>@import url('/rel.css');</style></head></html>"
    out = rewrite_html(html, base_url="https://example.com/dir/", proxy=_proxy)
    assert b"https%3A%2F%2Fexample.com%2Frel.css" in out


def test_rewrite_css_handles_import_and_url():
    from tinyagentos.routes.desktop_browser.rewriter import rewrite_css

    css = b'@import "a.css";\nbody{background:url(img/b.png)}'
    out = rewrite_css(css, base_url="https://example.com/s/main.css", proxy=_proxy).decode()
    assert "https%3A%2F%2Fexample.com%2Fs%2Fa.css" in out
    assert "https%3A%2F%2Fexample.com%2Fs%2Fimg%2Fb.png" in out


def test_data_uri_with_parentheses_survives():
    from tinyagentos.routes.desktop_browser.rewriter import rewrite_css

    svg = "url(data:image/svg+xml,%3Csvg fill='rgb(0,0,0)'%3E)"
    out = rewrite_css(f"a{{background:{svg}}}".encode(), base_url="https://example.com/", proxy=_proxy)
    assert svg.encode() in out


@pytest.mark.parametrize(
    "name, css_bytes",
    [
        pytest.param("url_repeated", b"url(" * 20000, id="url_repeated"),
        pytest.param("spaces_4k", b"url(" + b" " * 4096, id="spaces_4k"),
        pytest.param("nested", b"a{b:url(x" * 20000, id="nested"),
    ],
)
def test_pathological_url_input_is_bounded(name, css_bytes):
    """Hostile stylesheets must not stall the event loop: each input finishes under 2s."""
    import time

    from tinyagentos.routes.desktop_browser.rewriter import rewrite_css

    start = time.perf_counter()
    rewrite_css(css_bytes, base_url="https://example.com/", proxy=_proxy)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{name} ({len(css_bytes)} bytes) took {elapsed:.1f}s (must be <2.0s)"


_PROXIED_X = b"example.com%2Fx"


def _flood(n_bytes: int) -> bytes:
    return b"url(x)" * (n_bytes // 6)


@pytest.mark.parametrize(
    "name, html",
    [
        pytest.param(
            "style_block",
            b"<html><head><style>" + _flood(3_000_000) + b"</style></head></html>",
            id="style_block",
        ),
        pytest.param(
            "style_attr",
            b"<html><body><div style='" + _flood(3_000_000) + b"'></div></body></html>",
            id="style_attr",
        ),
    ],
)
def test_oversized_inline_css_is_dropped_not_rewritten(name, html):
    """A 3 MB url(x) flood inside HTML must neither be rewritten (~6s on the
    event loop, 5x output) nor served with its references intact."""
    import time

    start = time.perf_counter()
    out = rewrite_html(html, base_url="https://example.com/", proxy=_proxy)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{name} ({len(html)} bytes) took {elapsed:.1f}s (must be <2.0s)"
    assert _PROXIED_X not in out, f"{name}: oversized CSS was rewritten"
    assert b"url(x)" not in out, f"{name}: oversized CSS was passed through unproxied"
    assert len(out) < len(html), f"{name}: output {len(out)} bytes not shrunk"


def test_inline_css_budget_is_document_wide():
    """Several medium blocks whose SUM exceeds the budget: the first ones are
    rewritten, the rest dropped. A per-block cap would rewrite all of them."""
    block = b"<style>" + _flood(300_000) + b"</style>"
    html = b"<html><head>" + block * 3 + b"</head></html>"
    out = rewrite_html(html, base_url="https://example.com/", proxy=_proxy)
    assert _PROXIED_X in out, "first block within budget must still be rewritten"
    assert out.count(b"/* taOS: inline stylesheet too large, dropped */") == 2
    assert b"url(x)" not in out


def test_small_inline_css_is_still_rewritten():
    html = b"<html><head><style>a{background:url(x)}</style></head><body><p style='background:url(y)'></p></body></html>"
    out = rewrite_html(html, base_url="https://example.com/", proxy=_proxy)
    assert _PROXIED_X in out
    assert b"example.com%2Fy" in out


@pytest.mark.asyncio
class TestProxyRewritesCssResponse:
    @respx.mock
    async def test_text_css_response_is_rewritten(self, client):
        respx.get("http://example.com/s/main.css").mock(
            return_value=Response(
                200,
                content=b'@import "other.css"; a{background:url(i.png)}',
                headers={"content-type": "text/css; charset=utf-8"},
            )
        )
        with patch(
            "tinyagentos.routes.desktop_browser.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            resp = await client.get(
                "/api/desktop/browser/proxy",
                params={"profile_id": "personal", "url": "http://example.com/s/main.css"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")
        assert b"example.com%2Fs%2Fother.css" in resp.content
        assert b"example.com%2Fs%2Fi.png" in resp.content

    @respx.mock
    async def test_text_css_media_type_is_matched_case_insensitively(self, client):
        respx.get("http://example.com/s/upper.css").mock(
            return_value=Response(
                200,
                content=b'a{background:url(i.png)}',
                headers={"content-type": "Text/CSS; charset=utf-8"},
            )
        )
        with patch(
            "tinyagentos.routes.desktop_browser.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            resp = await client.get(
                "/api/desktop/browser/proxy",
                params={"profile_id": "personal", "url": "http://example.com/s/upper.css"},
            )
        assert resp.status_code == 200
        assert b"example.com%2Fs%2Fi.png" in resp.content

    @respx.mock
    async def test_oversized_css_body_is_refused(self, client):
        """CSS over 512 KiB is refused (502), never served with unproxied references."""
        # Larger than 512 KiB (524,288 bytes)
        oversized_content = b".class {" + b"url(x)" * 200000 + b"}"
        respx.get("http://example.com/oversized.css").mock(
            return_value=Response(
                200,
                content=oversized_content,
                headers={"content-type": "text/css; charset=utf-8"},
            )
        )
        with patch(
            "tinyagentos.routes.desktop_browser.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            resp = await client.get(
                "/api/desktop/browser/proxy",
                params={"profile_id": "personal", "url": "http://example.com/oversized.css"},
            )
        assert resp.status_code == 502
        assert "too large" in resp.json().get("error", "")
        assert b"url(x)" not in resp.content
