"""jsonutil: compact serialization with or without the accelerator."""

from hayate.jsonutil import dumps_compact


def test_compact_output():
    assert dumps_compact({"a": [1, 2], "b": "あ"}) == '{"a":[1,2],"b":"あ"}'


def test_stdlib_only_shapes_fall_back():
    # Int dict keys, huge ints, and exponent-notation floats are outside
    # the accelerator's scope; they still serialize via the stdlib path.
    assert dumps_compact({1: "a"}) == '{"1":"a"}'
    assert dumps_compact(10**20) == "100000000000000000000"
    assert dumps_compact(1e300) == "1e+300"
