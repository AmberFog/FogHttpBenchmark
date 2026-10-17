from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from foghttp_benchmark.isolation import perf_profile


DENSE_FREQUENCY_HZ = 1999
HEADER = (
    "# event : name = cpu-clock:u, , type = 1 (software), config = 0 (PERF_COUNT_SW_CPU_CLOCK), "
    "{ sample_period, sample_freq } = 499, sample_type = IP|TID|TIME|CALLCHAIN|PERIOD|STACK_USER, "
    "inherit = 1, exclude_kernel = 1, exclude_hv = 1, freq = 1, use_clockid = 1, "
    "sample_stack_user = 8192, clockid = 1\n"
)
SUMMARY = "# Total Lost Samples: 0\n# Samples: 2 of event 'cpu-clock:u'\n"
PERF_CODE = r"""
import json, os, pathlib, signal, sys, time
HEADER = HEADER_VALUE
SUMMARY = SUMMARY_VALUE
mode = MODE_VALUE
args=sys.argv[1:]
if args == ['version']:
    print('perf version fixture-1')
elif args[0]=='record':
    output=pathlib.Path(args[args.index('-o')+1])
    (output.parent/'profiler-pid').write_text(str(os.getpid()))
    if mode=='hang':
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(100)
    elif mode=='exit':
        raise SystemExit(23)
    pid=int(args[args.index('-p')+1])+(mode=='foreign')
    now=time.perf_counter_ns()
    time.sleep(.02)
    frequency=int(args[args.index('-F')+1])
    output.write_bytes(b'PERFILE2'+json.dumps({'pid':pid,'first':now,'last':time.perf_counter_ns(),'frequency':frequency}).encode())
    print('[ perf record: Captured bounded fixture ]',file=sys.stderr)
else:
    data=json.loads(pathlib.Path(args[args.index('-i')+1]).read_bytes()[8:])
    HEADER=HEADER.replace('= 499', '= %d' % data['frequency'])
    if args[0]=='script':
        print(HEADER,end='')
        for stamp in [data['first'],data['last']]:
            seconds,nanos=divmod(stamp,1_000_000_000)
            print('fixture %d/%d %d.%09d: 2004008 cpu-clock:u: ' % (data['pid'],data['pid'],seconds,nanos))
            print('\t 1234 real_fixture_leaf (/fixture/lib.so)\n')
    elif '--header-only' in args:
        print(HEADER,end='')
    else:
        print(SUMMARY,end='')
"""


def fake_perf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "ok") -> Path:
    tool = tmp_path / "owned-perf-fixture"
    tool.write_text(
        f"#!{sys.executable}\n"
        + PERF_CODE.replace("HEADER_VALUE", repr(HEADER))
        .replace("SUMMARY_VALUE", repr(SUMMARY))
        .replace("MODE_VALUE", repr(mode)),
    )
    tool.chmod(0o700)
    monkeypatch.setattr(perf_profile, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        perf_profile,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            perf_counter_ns=time.perf_counter_ns,
            get_clock_info=lambda _name: SimpleNamespace(
                implementation="clock_gettime(CLOCK_MONOTONIC)",
                monotonic=True,
                resolution=1e-9,
            ),
        ),
    )
    monkeypatch.setattr(perf_profile.shutil, "which", lambda _name: str(tool))
    return tool
