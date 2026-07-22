"""Tier 2 accelerator: behavioral identity with the stdlib encoder.

Skipped when hayate-accel is not built. Build locally with:

    uv run --with maturin maturin build --release -m accel/Cargo.toml -o dist-accel
    uv pip install dist-accel/*.whl
"""

import json

import pytest

accel = pytest.importorskip("hayate_accel", reason="hayate-accel is not built")

CASES = [
    None,
    True,
    False,
    "plain",
    'esc"ape\\\n\t\x01',
    "日本語",
    0,
    -5,
    12345678901234,
    1.0,
    -2.5,
    [],
    [1, "a", None],
    (1, 2),
    {},
    {"k": "v"},
    {"nested": {"list": [1, {"deep": True}]}, "n": 3.5},
]


@pytest.mark.parametrize("value", CASES, ids=repr)
def test_matches_stdlib(value):
    expected = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(accel.json_dumps(value)) == json.loads(expected)


def _multipart(boundary: str, *parts: bytes, close: bool = True) -> bytes:
    body = b"".join(b"--" + boundary.encode() + b"\r\n" + part for part in parts)
    return body + (b"--" + boundary.encode() + b"--\r\n" if close else b"")


MULTIPART_CASES = [
    ("empty", b"--b", b""),
    ("no-delimiter", b"--b", b"no delimiter at all"),
    (
        "simple",
        b"--b",
        _multipart("b", b'content-disposition: form-data; name="a"\r\n\r\nvalue\r\n'),
    ),
    (
        "text-and-binary-file",
        b"--b",
        _multipart(
            "b",
            b'content-disposition: form-data; name="text"\r\n'
            b"\r\nhello \xe4\xb8\x96\xe7\x95\x8c\r\n",
            b'content-disposition: form-data; name="f"; filename="x.bin"\r\n'
            b"content-type: application/octet-stream\r\n\r\n\x00\x01--almost\r\nnot-a-boundary\r\n",
        ),
    ),
    ("no-blank-line", b"--b", _multipart("b", b"headers-without-blank-line-so-skipped")),
    (
        "empty-value",
        b"--b",
        _multipart("b", b'content-disposition: form-data; name="e"\r\n\r\n\r\n'),
    ),
    (
        "missing-final-crlf",
        b"--b",
        _multipart("b", b'content-disposition: form-data; name="tail"\r\n\r\ntail', close=False),
    ),
    (
        "preamble",
        b"--b",
        b"junk\r\n" + _multipart("b", b'content-disposition: form-data; name="p"\r\n\r\nv\r\n'),
    ),
    (
        "consecutive-delimiters",
        b"--b7",
        b'--b7--b7\r\ncontent-disposition: form-data; name="late"\r\n\r\nx\r\n--b7--\r\n',
    ),
]


@pytest.mark.parametrize(
    ("delimiter", "body"),
    [(d, b) for _, d, b in MULTIPART_CASES],
    ids=[i for i, _, _ in MULTIPART_CASES],
)
def test_multipart_sections_match_pure_python(delimiter, body):
    """The Rust splitter and ``_py_sections`` must agree byte for byte."""
    from hayate.formdata import _py_sections

    assert accel.multipart_sections(body, delimiter) == _py_sections(body, delimiter)


def test_parse_multipart_is_identical_through_both_splitters(monkeypatch):
    """End to end: FormData built via the accelerator equals the pure path."""
    import hayate.formdata as formdata
    from hayate import File

    def snapshot(form):
        return [(n, (v.name, v.type, None) if isinstance(v, File) else v) for n, v in form], [
            v._data for _, v in form if isinstance(v, File)
        ]

    for _, delimiter, body in MULTIPART_CASES:
        boundary = delimiter[2:].decode()
        accelerated = snapshot(formdata.parse_multipart(body, boundary))
        monkeypatch.setattr(formdata, "_sections", formdata._py_sections)
        pure = snapshot(formdata.parse_multipart(body, boundary))
        monkeypatch.undo()
        assert accelerated == pure


def test_exact_text_for_common_shapes():
    assert accel.json_dumps({"id": "123"}) == '{"id":"123"}'
    assert accel.json_dumps([1, 2.5, "あ"]) == '[1,2.5,"あ"]'
    assert accel.json_dumps(1.0) == "1.0"


def test_unsupported_types_raise_type_error():
    with pytest.raises(TypeError):
        accel.json_dumps({1: "non-str-key"})
    with pytest.raises(TypeError):
        accel.json_dumps(object())
    with pytest.raises(TypeError):
        accel.json_dumps(10**20)
    with pytest.raises(TypeError):
        accel.json_dumps(float("nan"))
    with pytest.raises(TypeError):
        accel.json_dumps(1e300)  # exponent notation stays with the stdlib
