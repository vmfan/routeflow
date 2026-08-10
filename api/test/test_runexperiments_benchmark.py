from api.scripts import runexperiments


def test_benchmark_only_requires_fixture_mode(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "runexperiments",
            "--symbol",
            "ETHUSDT",
            "--side",
            "buy",
            "--benchmark-only",
        ],
    )

    try:
        runexperiments.main()
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "--benchmark-only currently requires --fixture"