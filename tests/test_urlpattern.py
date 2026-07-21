"""URLPattern: documented v0.1 pathname subset."""

import pytest

from hayate import URLPattern


def test_static():
    p = URLPattern("/health")
    assert p.test("/health")
    assert not p.test("/health/")
    result = p.exec("/health")
    assert result is not None
    assert result.pathname.groups == {}
    assert result.pathname.input == "/health"
    assert p.exec("/nope") is None


def test_named_param():
    p = URLPattern("/books/:id")
    result = p.exec("/books/42")
    assert result is not None
    assert result.pathname.groups == {"id": "42"}
    assert p.exec("/books/") is None
    assert p.exec("/books/1/2") is None


def test_multiple_params():
    p = URLPattern("/api/:version/users/:id")
    result = p.exec("/api/v2/users/10")
    assert result is not None
    assert result.pathname.groups == {"version": "v2", "id": "10"}


def test_regex_param():
    p = URLPattern(r"/books/:id(\d+)")
    assert p.test("/books/123")
    assert not p.test("/books/abc")


def test_wildcard():
    p = URLPattern("/files/*")
    result = p.exec("/files/a/b.txt")
    assert result is not None
    assert result.pathname.groups == {"0": "a/b.txt"}
    empty = p.exec("/files/")
    assert empty is not None
    assert empty.pathname.groups == {"0": ""}
    assert p.exec("/files") is None


def test_optional_param_absorbs_slash_prefix():
    p = URLPattern("/posts/:id?")
    with_id = p.exec("/posts/7")
    assert with_id is not None
    assert with_id.pathname.groups == {"id": "7"}
    without = p.exec("/posts")
    assert without is not None
    assert without.pathname.groups == {"id": None}
    assert p.exec("/posts/") is None


def test_escaped_syntax_char_is_literal():
    p = URLPattern(r"/api/v1\:verify")
    assert p.test("/api/v1:verify")
    assert not p.test("/api/v1verify")


def test_duplicate_name_rejected():
    with pytest.raises(ValueError):
        URLPattern("/a/:x/:x")


def test_unsupported_syntax_rejected():
    with pytest.raises(ValueError):
        URLPattern("/a/{b}")
    with pytest.raises(ValueError):
        URLPattern("/a/:x+")
    with pytest.raises(ValueError):
        URLPattern("/a/:x*")
    with pytest.raises(ValueError):
        URLPattern("/a/:x(a(b)c)")  # capturing group inside a matcher


def test_colon_without_name_rejected():
    with pytest.raises(ValueError):
        URLPattern("/a/:/b")
