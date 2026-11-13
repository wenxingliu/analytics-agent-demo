from evals.cost import add_usage, cost, load_pricing


def test_cost_uses_each_token_kind_price():
    pricing = {"m": {"input": 2.0, "cached_input": 0.2, "output": 10.0}}
    usage = {"m": {"calls": 3, "input": 1_000_000, "cached_input": 500_000, "output": 100_000}}
    assert cost(usage, pricing) == 2.0 + 0.1 + 1.0


def test_unknown_model_has_no_price_and_empty_usage_is_free():
    assert (
        cost({"other": {"input": 10}}, {"m": {"input": 1, "cached_input": 0, "output": 1}}) is None
    )
    assert cost({}, {}) == 0


def test_add_usage_sums_per_model():
    a = {"m": {"calls": 1, "input": 10, "output": 1}}
    b = {"m": {"calls": 2, "input": 5, "output": 2}, "j": {"calls": 1, "input": 1}}
    assert add_usage(a, b) == {
        "m": {"calls": 3, "input": 15, "output": 3},
        "j": {"calls": 1, "input": 1},
    }


def test_pricing_file_has_every_field():
    for model, price in load_pricing().items():
        assert set(price) == {"input", "cached_input", "output"}, model
