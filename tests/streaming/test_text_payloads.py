from foghttp_benchmark.streaming.text_payloads import streaming_text_payloads


TEXT_64K_BYTES = 65_536
LINES_10K = 10_000
UNICODE_LINES = 512


def test_text_payloads_define_line_counts_and_utf8_boundaries() -> None:
    payloads = streaming_text_payloads()

    assert payloads["text-64k"].size_bytes == TEXT_64K_BYTES
    assert payloads["lines-10k"].line_count == LINES_10K
    assert payloads["lines-10k"].body.count(b"\n") == LINES_10K
    assert payloads["unicode-lines"].line_count == UNICODE_LINES
    assert "\U0001f680" in payloads["unicode-lines"].body.decode()
    assert payloads["long-line-1m"].line_count == 1
