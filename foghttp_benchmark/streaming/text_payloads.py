__all__ = (
    "TEXT_STREAM_CONTENT_TYPE",
    "TextPayload",
    "streaming_text_payloads",
)

from dataclasses import dataclass
from functools import lru_cache


TEXT_STREAM_CONTENT_TYPE = b"text/plain; charset=utf-8"
TEXT_64K_BYTES = 65_536
LINES_10K = 10_000
DRIP_LINES = 512
UNICODE_LINES = 512
LONG_LINE_CHARS = 1_048_576


@dataclass(frozen=True, slots=True)
class TextPayload:
    name: str
    body: bytes
    line_count: int | None

    @property
    def size_bytes(self) -> int:
        return len(self.body)


@lru_cache(maxsize=1)
def streaming_text_payloads() -> dict[str, TextPayload]:
    return {
        "text-64k": TextPayload(
            name="text-64k",
            body=_fixed_ascii_text(TEXT_64K_BYTES),
            line_count=None,
        ),
        "lines-10k": TextPayload(
            name="lines-10k",
            body=_line_payload(LINES_10K),
            line_count=LINES_10K,
        ),
        "drip-lines": TextPayload(
            name="drip-lines",
            body=_line_payload(DRIP_LINES),
            line_count=DRIP_LINES,
        ),
        "unicode-lines": TextPayload(
            name="unicode-lines",
            body=_unicode_line_payload(UNICODE_LINES),
            line_count=UNICODE_LINES,
        ),
        "long-line-1m": TextPayload(
            name="long-line-1m",
            body=("x" * LONG_LINE_CHARS + "\n").encode(),
            line_count=1,
        ),
    }


def _fixed_ascii_text(size_bytes: int) -> bytes:
    unit = b"FogHTTP text streaming payload 0123456789 abcdefghijklmnopqrstuvwxyz\n"
    repeats = (size_bytes // len(unit)) + 1
    return (unit * repeats)[:size_bytes]


def _line_payload(line_count: int) -> bytes:
    return "".join(f"line-{index:05d} payload abcdefghijklmnopqrstuvwxyz\n" for index in range(line_count)).encode()


def _unicode_line_payload(line_count: int) -> bytes:
    return "".join(
        f"unicode-{index:05d} cafe \u03bb \u2603 \U0001f680 payload\r\n" for index in range(line_count)
    ).encode()
