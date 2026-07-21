"""Headers: Fetch Standard semantics."""

import pytest

from hayate import Headers


def test_case_insensitive_get_set():
    h = Headers()
    h.set("Content-Type", "text/plain")
    assert h.get("content-type") == "text/plain"
    assert h.has("CONTENT-TYPE")
    assert "Content-Type" in h


def test_append_combines_on_get():
    h = Headers()
    h.append("Accept", "text/html")
    h.append("accept", "application/json")
    assert h.get("accept") == "text/html, application/json"


def test_set_replaces_all_values():
    h = Headers([("x-a", "1"), ("x-a", "2")])
    h.set("x-a", "3")
    assert h.raw() == [("x-a", "3")]


def test_delete_removes_all_values():
    h = Headers([("x-a", "1"), ("x-b", "2"), ("x-a", "3")])
    h.delete("X-A")
    assert h.raw() == [("x-b", "2")]
    assert h.get("x-a") is None


def test_set_cookie_not_combined():
    h = Headers()
    h.append("set-cookie", "a=1")
    h.append("set-cookie", "b=2")
    assert h.set_cookie_list() == ["a=1", "b=2"]
    items = list(h.items())
    assert ("set-cookie", "a=1") in items
    assert ("set-cookie", "b=2") in items


def test_items_sorted_and_combined():
    h = Headers([("b", "2"), ("a", "1"), ("b", "3")])
    assert list(h.items()) == [("a", "1"), ("b", "2, 3")]
    assert list(h.keys()) == ["a", "b"]


def test_immutable_guard():
    h = Headers({"a": "1"}, guard="immutable")
    with pytest.raises(TypeError):
        h.set("a", "2")
    with pytest.raises(TypeError):
        h.append("b", "2")
    with pytest.raises(TypeError):
        h.delete("a")
    assert h.get("a") == "1"


def test_invalid_name_rejected():
    with pytest.raises(ValueError):
        Headers([("bad name", "v")])


def test_invalid_value_rejected():
    with pytest.raises(ValueError):
        Headers([("x", "a\r\nb")])


def test_value_whitespace_normalized():
    h = Headers([("x", "  padded \t")])
    assert h.get("x") == "padded"


def test_init_from_headers_copies():
    a = Headers({"x": "1"})
    b = Headers(a)
    b.set("x", "2")
    assert a.get("x") == "1"
    assert b.get("x") == "2"


def test_equality_ignores_order():
    assert Headers([("a", "1"), ("b", "2")]) == Headers([("b", "2"), ("a", "1")])
