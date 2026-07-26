"""jsonutil: compact serialization with or without the accelerator."""

from hayate.jsonutil import dumps_compact


def test_compact_output():
    assert dumps_compact({"a": [1, 2], "b": "あ"}) == '{"a":[1,2],"b":"あ"}'


def test_flat_dict_fast_path_matches_json_semantics():
    assert dumps_compact(
        {
            'escape"': "line\nあ",
            "none": None,
            "yes": True,
            "no": False,
            "big": 10**30,
        }
    ) == (
        '{"escape\\"":"line\\nあ","none":null,"yes":true,'
        '"no":false,"big":1000000000000000000000000000000}'
    )


def test_stdlib_only_shapes_fall_back():
    # Int dict keys, huge ints, and exponent-notation floats are outside
    # the accelerator's scope; they still serialize via the stdlib path.
    assert dumps_compact({1: "a"}) == '{"1":"a"}'
    assert dumps_compact(10**20) == "100000000000000000000"
    assert dumps_compact(1e300) == "1e+300"
