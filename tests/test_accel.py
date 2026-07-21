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
