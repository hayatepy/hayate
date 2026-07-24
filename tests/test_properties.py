"""Property-based invariants across the parser and routing trust boundaries."""

from __future__ import annotations

import string

from hypothesis import example, given
from hypothesis import strategies as st

from hayate import URL, Headers, URLPattern, URLSearchParams
from hayate.cookies import parse_cookies, serialize_set_cookie
from hayate.router import Route, Router

_UNICODE_SCALAR = st.characters(codec="utf-8")
_TEXT = st.text(_UNICODE_SCALAR, max_size=40)
_TOKEN_ALPHABET = "!#$%&'*+-.^_`|~" + string.ascii_letters + string.digits
_TOKEN = st.text(_TOKEN_ALPHABET, min_size=1, max_size=24)
_HEADER_VALUE = st.text(
    st.characters(min_codepoint=0x20, max_codepoint=0xFF, exclude_characters="\x7f"),
    max_size=40,
)
_SEGMENT = st.text(string.ascii_lowercase + string.digits + "_-", min_size=1, max_size=8)
_PATH = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda segments: "/" + "/".join(segments))


@st.composite
def _pattern(draw: st.DrawFn) -> str:
    segments = draw(st.lists(st.one_of(_SEGMENT, st.none()), min_size=1, max_size=4))
    parameter = iter(("a", "b", "c", "d"))
    return "/" + "/".join(
        segment if segment is not None else f":{next(parameter)}" for segment in segments
    )


@given(st.text(max_size=100))
@example("http://日本語.example/道")
@example("http://example.com/\ud800")
def test_url_parser_never_leaks_internal_unicode_errors(raw: str) -> None:
    try:
        parsed = URL(raw)
    except ValueError:
        return
    assert URL(parsed.href).href == parsed.href


@given(st.lists(st.tuples(_TEXT, _TEXT), max_size=20))
def test_search_params_serialize_parse_roundtrip(pairs: list[tuple[str, str]]) -> None:
    encoded = str(URLSearchParams(pairs))
    assert list(URLSearchParams(encoded)) == pairs


@given(st.lists(st.tuples(_TOKEN, _HEADER_VALUE), max_size=20))
def test_headers_preserve_valid_pairs_and_normalize_names(
    pairs: list[tuple[str, str]],
) -> None:
    headers = Headers(pairs)
    assert headers.raw() == [(name.lower(), value.strip(" \t")) for name, value in pairs]
    assert Headers(headers) == headers


@given(_TOKEN, st.text(string.ascii_letters + string.digits + "-._~", max_size=40))
def test_cookie_serialization_roundtrips_name_and_value(name: str, value: str) -> None:
    encoded = serialize_set_cookie(name, value)
    assert parse_cookies(encoded.split(";", 1)[0]) == {name: value}


@given(st.lists(_pattern(), min_size=1, max_size=20, unique=True), _PATH)
def test_router_matches_the_public_urlpattern_semantics(patterns: list[str], path: str) -> None:
    router = Router()
    for pattern in patterns:
        router.add(Route("GET", pattern, lambda: None))

    static = next((pattern for pattern in patterns if pattern == path), None)
    dynamic = next(
        (pattern for pattern in patterns if ":" in pattern and URLPattern(pattern).test(path)),
        None,
    )
    expected = static or dynamic
    matched = router.match("GET", path)
    assert (matched[0].pattern if matched is not None else None) == expected
