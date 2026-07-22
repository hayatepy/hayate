"""Routing semantics across the three tiers (static / trie / regex).

The tiering is an implementation detail — these tests pin that it stays
invisible: registration order decides between overlapping dynamic
routes exactly as a single linear scan would.
"""

from hayate.router import Route, Router


def _router(*routes: tuple[str, str]) -> Router:
    router = Router()
    for method, pattern in routes:
        router.add(Route(method, pattern, f"{method} {pattern}"))
    return router


def test_registration_order_wins_across_tiers_regex_first():
    router = _router(("GET", r"/users/:id(\d+)"), ("GET", "/users/:name"))
    route, params = router.match("GET", "/users/42")
    assert route.handler == r"GET /users/:id(\d+)"
    assert params == {"id": "42"}
    route, params = router.match("GET", "/users/abc")  # constraint fails
    assert route.handler == "GET /users/:name"
    assert params == {"name": "abc"}


def test_registration_order_wins_across_tiers_trie_first():
    router = _router(("GET", "/users/:name"), ("GET", r"/users/:id(\d+)"))
    route, params = router.match("GET", "/users/42")
    assert route.handler == "GET /users/:name"
    assert params == {"name": "42"}


def test_trie_backtracks_from_a_literal_dead_end():
    router = _router(("GET", "/a/b/:x"), ("GET", "/a/:y/d"))
    route, params = router.match("GET", "/a/b/d")
    # The literal branch (a -> b) dead-ends at "d"; the parameter branch
    # must still be found.
    assert route.handler == "GET /a/b/:x"  # b matches literally, d binds :x
    assert params == {"x": "d"}
    route, params = router.match("GET", "/a/z/d")
    assert route.handler == "GET /a/:y/d"
    assert params == {"y": "z"}


def test_overlapping_trie_routes_settle_by_registration_index():
    router = _router(("GET", "/:y/b/c"), ("GET", "/a/:x/c"))
    route, params = router.match("GET", "/a/b/c")  # both shapes match
    assert route.handler == "GET /:y/b/c"
    assert params == {"y": "a"}


def test_same_shape_parameters_keep_the_first_registration():
    router = _router(("GET", "/u/:a"), ("GET", "/u/:b"))
    route, params = router.match("GET", "/u/x")
    assert route.handler == "GET /u/:a"
    assert params == {"a": "x"}


def test_trailing_slash_is_significant():
    router = _router(("GET", "/t/:id/"))
    assert router.match("GET", "/t/x/") is not None
    assert router.match("GET", "/t/x") is None


def test_parameters_do_not_match_an_empty_segment():
    router = _router(("GET", "/x/:p/y"))
    assert router.match("GET", "/x//y") is None
    assert router.match("GET", "/x/v/y") is not None


def test_percent_encoded_segments_stay_raw_in_params():
    router = _router(("GET", "/items/:name"))
    _, params = router.match("GET", "/items/%E3%81%82")
    assert params == {"name": "%E3%81%82"}  # decoding happens in HayateRequest


def test_allowed_methods_sees_every_tier():
    router = _router(
        ("GET", "/r/:id"),  # trie
        ("POST", r"/r/:id(\d+)"),  # regex tail
        ("#websocket", "/r/:id"),  # excluded from Allow
    )
    router.add(Route("PUT", "/r/1", "static"))
    assert router.allowed_methods("/r/1") == ["GET", "HEAD", "POST", "PUT"]
    assert router.allowed_methods("/r/abc") == ["GET", "HEAD"]


def test_wildcards_and_optionals_stay_on_the_regex_tail():
    router = _router(("GET", "/files/*"), ("GET", "/opt/:v?"))
    route, params = router.match("GET", "/files/a/b.txt")
    assert route.handler == "GET /files/*"
    assert params == {"0": "a/b.txt"}  # unnamed wildcards are numbered, per URLPattern
    route, params = router.match("GET", "/opt")
    assert route.handler == "GET /opt/:v?"
