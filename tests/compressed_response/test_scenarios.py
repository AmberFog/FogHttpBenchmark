import gzip
import zlib

import brotli

from foghttp_benchmark.compressed_response.payloads import (
    COMPRESSED_RESPONSE_BODIES,
    HIGH_RATIO_BODY,
)
from foghttp_benchmark.compressed_response.scenarios import compressed_response_scenarios
from foghttp_benchmark.constants import COMPRESSED_RESPONSE_SUITE
from foghttp_benchmark.validation import validate_suite


def test_compressed_response_payloads_decode_to_expected_bodies() -> None:
    gzip_body = COMPRESSED_RESPONSE_BODIES["gzip-64k"]
    deflate_body = COMPRESSED_RESPONSE_BODIES["deflate-64k"]
    brotli_body = COMPRESSED_RESPONSE_BODIES["br-64k"]
    multi_body = COMPRESSED_RESPONSE_BODIES["multi-gzip-deflate-64k"]

    assert gzip.decompress(gzip_body.encoded_body) == gzip_body.decoded_body
    assert zlib.decompress(deflate_body.encoded_body) == deflate_body.decoded_body
    assert brotli.decompress(brotli_body.encoded_body) == brotli_body.decoded_body
    assert gzip.decompress(zlib.decompress(multi_body.encoded_body)) == multi_body.decoded_body


def test_compressed_response_scenarios_expose_decoded_lengths() -> None:
    scenarios = compressed_response_scenarios()

    assert set(scenarios) == set(COMPRESSED_RESPONSE_BODIES)
    assert scenarios["gzip-high-ratio-1m"].expected_content_length == len(HIGH_RATIO_BODY)
    assert scenarios["gzip-json-small"].expected_json_keys == ("ok", "message", "items")


def test_compressed_response_suite_is_known() -> None:
    validate_suite(COMPRESSED_RESPONSE_SUITE)
