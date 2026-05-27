from foghttp_benchmark.streaming.cases import streaming_cases


EXPECTED_LINES_10K = 10_000


def test_streaming_cases_define_explicit_drip_routes() -> None:
    cases = streaming_cases()

    assert set(cases) == {
        "drip-64k-1ms",
        "drip-lines-1ms",
        "first-chunk-close-1m",
        "first-line-close-10k",
        "lines-10k",
        "long-line-1m",
        "stream-1m",
        "stream-64k",
        "text-64k",
        "unicode-lines",
    }
    assert cases["stream-64k"].path == "/drip-bytes/65536/8192/0"
    assert cases["stream-64k"].read == "bytes"
    assert cases["stream-64k"].consume == "all"
    assert cases["first-chunk-close-1m"].consume == "first-chunk"
    assert cases["text-64k"].read == "text"
    assert cases["lines-10k"].read == "lines"
    assert cases["lines-10k"].expected_lines == EXPECTED_LINES_10K
    assert cases["unicode-lines"].path == "/drip-text/unicode-lines/7/0"
    assert cases["first-line-close-10k"].consume == "first-line"
