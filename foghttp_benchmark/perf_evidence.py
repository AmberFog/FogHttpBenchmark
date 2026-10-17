__all__ = ("DEFAULT_PERF_SAMPLE_FREQUENCY_HZ", "PERF_SAMPLE_FREQUENCIES_HZ", "inspect_perf_text")

from decimal import Decimal
import re

from foghttp_benchmark.models import JsonObject


DEFAULT_PERF_SAMPLE_FREQUENCY_HZ = 499
PERF_SAMPLE_FREQUENCIES_HZ = frozenset({499, 1999})
_SAMPLE = re.compile(
    r"^\s*\S.*?\s+(?P<pid>\d+)\s*/\s*(?P<tid>\d+)\s+"
    r"(?P<time>\d+\.\d{9}):\s+(?P<period>\d+)\s+(?P<event>[^\s]+):(?:\s|$)",
)
_EVENT_MARKER = re.compile(r"\d+\.\d+:\s+(?:\d+\s+)?[^\s]+:")
_LOST = re.compile(r"PERF_RECORD_(?:LOST|LOST_SAMPLES|THROTTLE|UNTHROTTLE)|\btruncat", re.IGNORECASE)
_REQUIRED_ATTRIBUTES = {
    "type": r"1(?:\s*\(software\))?",
    "config": r"0(?:\s*\(PERF_COUNT_SW_CPU_CLOCK\))?",
    "exclude_kernel": "1",
    "exclude_hv": "1",
    "use_clockid": "1",
    "clockid": "1",
    "freq": "1",
    "sample_stack_user": "8192",
}


def _inspect_event(header: str, sample_frequency_hz: int) -> None:
    if type(sample_frequency_hz) is not int or sample_frequency_hz not in PERF_SAMPLE_FREQUENCIES_HZ:
        msg = "Perf sampling frequency must be 499 or 1999 Hz"
        raise ValueError(msg)
    events = [line for line in header.splitlines() if line.startswith("# event :")]
    if len(events) != 1 or not re.search(r"\bname\s*=\s*cpu-clock:u,", events[0]):
        msg = "Perf recording must contain exactly the cpu-clock:u event"
        raise ValueError(msg)
    event = events[0]
    if not re.search(rf"\{{\s*sample_period,\s*sample_freq\s*\}}\s*=\s*{sample_frequency_hz}(?:,|\s*$)", event):
        msg = f"Perf recording does not prove the declared {sample_frequency_hz} Hz sampling frequency"
        raise ValueError(msg)
    for attribute, value in _REQUIRED_ATTRIBUTES.items():
        if not re.search(rf"(?:^|,\s*){attribute}\s*=\s*{value}(?:,|\s*$)", event):
            msg = f"Perf recording does not prove required event attribute {attribute}"
            raise ValueError(msg)
    if not re.search(r"sample_type\s*=\s*[^,]*\bTIME\b[^,]*\bSTACK_USER\b", event):
        msg = "Perf recording must retain timestamped user stack samples"
        raise ValueError(msg)


def inspect_perf_text(
    *,
    header: str,
    script: str,
    summary: str,
    record_stderr: str,
    pid: int,
    sample_frequency_hz: int = DEFAULT_PERF_SAMPLE_FREQUENCY_HZ,
) -> JsonObject:
    """Check the explicit user CPU event and decoded sample identity without reading perf.data as Python data."""
    _inspect_event(header, sample_frequency_hz)
    if not re.search(r"^# Total Lost Samples:\s+0\s*$", summary, re.MULTILINE):
        msg = "Perf report does not prove zero lost samples"
        raise ValueError(msg)
    if _LOST.search(script) or _LOST.search(record_stderr):
        msg = "Perf recording contains lost, throttled or truncated records"
        raise ValueError(msg)
    timestamps: list[int] = []
    tids: set[int] = set()
    period_sum = 0
    for line in script.splitlines():
        if not line or line.startswith("#"):
            continue
        sample = _SAMPLE.match(line)
        if sample is None:
            if _EVENT_MARKER.search(line):
                msg = "Perf script contains a sample without explicit PID/TID and nanosecond clock evidence"
                raise ValueError(msg)
            continue
        if int(sample["pid"]) != pid or sample["event"] != "cpu-clock:u":
            msg = "Perf sample event/PID differs from the owned target"
            raise ValueError(msg)
        timestamps.append(int(Decimal(sample["time"]) * 1_000_000_000))
        tids.add(int(sample["tid"]))
        period_sum += int(sample["period"])
    reported = re.search(r"^# Samples:\s+(\d+)\s+of event 'cpu-clock:u'\s*$", summary, re.MULTILINE)
    if reported is not None and int(reported.group(1)) != len(timestamps):
        msg = "Perf decoded sample count differs from the exact report summary count"
        raise ValueError(msg)
    return {
        "sample_count": len(timestamps),
        "sample_pids": [pid] if timestamps else [],
        "sample_tids": sorted(tids),
        "sample_period_sum": period_sum,
        "first_sample_ns": min(timestamps) if timestamps else None,
        "last_sample_ns": max(timestamps) if timestamps else None,
        "event": "cpu-clock:u",
        "event_type": 1,
        "event_config": 0,
        "exclude_kernel": True,
        "exclude_hv": True,
        "clockid": 1,
        "lost_samples": 0,
    }
