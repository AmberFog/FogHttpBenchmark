from copy import deepcopy
from pathlib import Path

from tests.streaming.test_lifecycle_reports import (
    CLIENT_RSS_BYTES,
    LIFETIME_RSS_BYTES,
    SERVER_RSS_BYTES,
    result,
    write_results,
)


def test_lifecycle_keeps_nullable_role_peaks_zero_and_original_unavailability(tmp_path: Path) -> None:
    missing = result()
    zero = result(repeat=2)
    missing["resources"]["sampled_peaks"]["client"] = {"rss_bytes": None, "threads": None, "fds": None}
    zero["resources"]["sampled_peaks"]["client"] = {"rss_bytes": 0, "threads": 0, "fds": None}
    original = deepcopy([missing, zero])

    payload = write_results(tmp_path, [missing, zero])
    row = payload["aggregate"][0]
    client = row["resources"]["client"]
    server = row["resources"]["server"]

    assert payload["runs"] == original
    assert client["sampled_peak_rss_bytes_max"] == 0
    assert client["sampled_peak_threads_max"] == 0
    assert client["sampled_peak_fds_max"] is None
    assert client["unavailable"]["fds"] == ["unsupported"]
    assert client["lifetime_high_water_rss_bytes_max"] == LIFETIME_RSS_BYTES
    assert server["sampled_peak_rss_bytes_max"] == SERVER_RSS_BYTES
    assert server["lifetime_high_water_rss_bytes_max"] is None
    assert original[0]["resources"]["samples"][0]["rss_bytes"] == CLIENT_RSS_BYTES
