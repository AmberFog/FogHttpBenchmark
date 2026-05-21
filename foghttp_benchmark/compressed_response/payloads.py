__all__ = (
    "COMPRESSED_RESPONSE_BODIES",
    "HIGH_RATIO_BODY",
    "CompressedResponseBody",
    "compressed_response_body",
)

from dataclasses import dataclass
import gzip
import zlib

import brotli  # type: ignore[import-untyped]

from foghttp_benchmark.scenarios import BYTES_64K, SMALL_JSON


HIGH_RATIO_BODY = b"a" * 1_048_576


@dataclass(frozen=True, slots=True)
class CompressedResponseBody:
    decoded_body: bytes
    encoded_body: bytes
    content_type: bytes
    content_encoding_headers: tuple[str, ...]


def compressed_response_body(
    *,
    decoded_body: bytes,
    content_type: bytes,
    encodings: tuple[str, ...],
) -> CompressedResponseBody:
    encoded_body = decoded_body
    for encoding in encodings:
        encoded_body = encode_body(encoded_body, encoding)
    return CompressedResponseBody(
        decoded_body=decoded_body,
        encoded_body=encoded_body,
        content_type=content_type,
        content_encoding_headers=encodings,
    )


def encode_body(body: bytes, encoding: str) -> bytes:
    if encoding == "gzip":
        return gzip.compress(body)
    if encoding == "deflate":
        return zlib.compress(body)
    if encoding == "br":
        return bytes(brotli.compress(body))
    msg = f"unsupported compressed benchmark encoding: {encoding}"
    raise ValueError(msg)


COMPRESSED_RESPONSE_BODIES: dict[str, CompressedResponseBody] = {
    "gzip-json-small": compressed_response_body(
        decoded_body=SMALL_JSON,
        content_type=b"application/json",
        encodings=("gzip",),
    ),
    "gzip-64k": compressed_response_body(
        decoded_body=BYTES_64K,
        content_type=b"application/octet-stream",
        encodings=("gzip",),
    ),
    "deflate-64k": compressed_response_body(
        decoded_body=BYTES_64K,
        content_type=b"application/octet-stream",
        encodings=("deflate",),
    ),
    "br-64k": compressed_response_body(
        decoded_body=BYTES_64K,
        content_type=b"application/octet-stream",
        encodings=("br",),
    ),
    "gzip-high-ratio-1m": compressed_response_body(
        decoded_body=HIGH_RATIO_BODY,
        content_type=b"application/octet-stream",
        encodings=("gzip",),
    ),
    "multi-gzip-deflate-64k": compressed_response_body(
        decoded_body=BYTES_64K,
        content_type=b"application/octet-stream",
        encodings=("gzip", "deflate"),
    ),
}
