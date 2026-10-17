__all__ = ("streaming_bytes_payload", "streaming_bytes_sha256")

from functools import lru_cache
from hashlib import sha256


BYTE_PATTERN = bytes(range(256))
DIGEST_BLOCK = BYTE_PATTERN * 256


def streaming_bytes_payload(size_bytes: int) -> bytes:
    repeats, remaining = divmod(size_bytes, len(BYTE_PATTERN))
    return BYTE_PATTERN * repeats + BYTE_PATTERN[:remaining]


@lru_cache(maxsize=16)
def streaming_bytes_sha256(size_bytes: int) -> str:
    digest = sha256()
    blocks, remaining = divmod(size_bytes, len(DIGEST_BLOCK))
    for _block in range(blocks):
        digest.update(DIGEST_BLOCK)
    digest.update(DIGEST_BLOCK[:remaining])
    return digest.hexdigest()
