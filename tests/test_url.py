"""URL / URLSearchParams: WHATWG semantics (documented subset)."""

import pytest

from hayate import URL, URLSearchParams


def test_basic_components():
    u = URL("https://user:pw@Example.COM:8080/path/to%20x?q=1&q=2#frag")
    assert u.protocol == "https:"
    assert u.username == "user"
    assert u.password == "pw"
    assert u.hostname == "example.com"
    assert u.port == "8080"
    assert u.host == "example.com:8080"
    assert u.pathname == "/path/to%20x"
    assert u.search == "?q=1&q=2"
    assert u.hash == "#frag"
    assert u.origin == "https://example.com:8080"


def test_default_port_dropped():
    assert URL("http://a.com:80/").port == ""
    assert URL("https://a.com:443/x").port == ""
    assert URL("https://a.com:8443/").port == "8443"


def test_empty_path_becomes_root():
    assert URL("http://a.com").pathname == "/"


def test_dot_segments_removed():
    assert URL("http://a.com/a/b/../c/./d").pathname == "/a/c/d"
    assert URL("http://a.com/a/b/..").pathname == "/a/"


def test_path_percent_encoding_normalized():
    assert URL("http://a.com/日本 語").pathname == "/%E6%97%A5%E6%9C%AC%20%E8%AA%9E"
    # Existing escapes are preserved, never double-encoded.
    assert URL("http://a.com/a%20b").pathname == "/a%20b"


def test_whitespace_and_backslash_tolerance():
    # URL Standard preprocessing: strip C0/space, drop tab/newline.
    assert URL("  http://a.com/x\n").href == "http://a.com/x"
    # Special schemes treat "\" as "/" and tolerate slash miscounts.
    assert URL("http:\\\\a.com\\x").href == "http://a.com/x"
    assert URL("http:a.com/x").hostname == "a.com"


def test_search_params_decoding():
    u = URL("http://a.com/?a=1&a=2&b=%E3%81%82&c=x+y")
    p = u.search_params
    assert p.get("a") == "1"
    assert p.get_all("a") == ["1", "2"]
    assert p.get("b") == "あ"
    assert p.get("c") == "x y"


def test_invalid_urls():
    with pytest.raises(ValueError):
        URL("not a url")
    with pytest.raises(ValueError):
        URL("http://")
    with pytest.raises(ValueError):
        URL("mailto:x@y.com")  # no authority: outside the documented subset


def test_base_resolution():
    base = URL("http://a.com/dir/page?x=1")
    assert URL("/abs", base).href == "http://a.com/abs"
    assert URL("?q=2", base).href == "http://a.com/dir/page?q=2"
    assert URL("child", base).href == "http://a.com/dir/child"
    assert URL("//b.com/x", base).href == "http://b.com/x"


def test_ipv6_host():
    u = URL("http://[::1]:8000/x")
    assert u.hostname == "[::1]"
    assert u.port == "8000"


def test_href_roundtrip():
    href = "https://example.com/a?b=c#d"
    assert URL(href).href == href
    assert str(URL(href)) == href


def test_equality():
    assert URL("http://a.com/x") == URL("http://A.COM/x")


class TestURLSearchParams:
    def test_parse_and_serialize_roundtrip(self):
        p = URLSearchParams("a=1&b=hello+world&c=%2F")
        assert p.get("b") == "hello world"
        assert p.get("c") == "/"
        assert str(p) == "a=1&b=hello+world&c=%2F"

    def test_set_append_delete(self):
        p = URLSearchParams()
        p.append("k", "1")
        p.append("k", "2")
        p.set("k", "3")
        assert p.get_all("k") == ["3"]
        p.delete("k")
        assert len(p) == 0

    def test_has_with_value(self):
        p = URLSearchParams("a=1&a=2")
        assert p.has("a")
        assert p.has("a", "2")
        assert not p.has("a", "3")

    def test_sort_is_stable_by_name(self):
        p = URLSearchParams("b=2&a=1&c=3")
        p.sort()
        assert str(p) == "a=1&b=2&c=3"

    def test_unicode_encoding(self):
        p = URLSearchParams()
        p.append("q", "日本語")
        assert str(p) == "q=%E6%97%A5%E6%9C%AC%E8%AA%9E"

    def test_tilde_encoded_per_form_urlencoded(self):
        # Unlike urllib.parse.quote, the URL Standard's form-urlencoded
        # serializer percent-encodes "~".
        p = URLSearchParams()
        p.append("x", "~")
        assert str(p) == "x=%7E"

    def test_init_from_pairs_and_mapping(self):
        assert str(URLSearchParams([("a", "1"), ("a", "2")])) == "a=1&a=2"
        assert str(URLSearchParams({"a": "1"})) == "a=1"
