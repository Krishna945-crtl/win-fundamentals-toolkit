# Windows Fundamentals Toolkit

A Python toolkit that studies the **performance, battery life and reliability** of a Windows laptop
using real telemetry and Windows Event Logs – the same fundamentals that device and OS teams track at scale.

It answers three questions about a device:

1. **How loaded is it?** CPU and memory at P50 / P95 / max, sampled every few seconds
2. **What drains the battery and causes slowdowns?** Battery % lost per hour on battery power, and which
   process was on top during every CPU spike
3. **How reliable is it?** App crashes, hangs, unexpected shutdowns, driver, service, disk and hardware
   errors from the Windows Event Logs, rolled into a daily reliability score out of 10

## How it works

| Part | What it does |
|---|---|
| `wft/collector.py` | Samples system CPU, memory, disk I/O, battery and the top 5 processes every N seconds with `psutil`, appending to CSV (telemetry) |
| `wft/perf_report.py` | pandas analysis: percentiles, battery drain per unplugged session (sleep gaps excluded), top CPU consumers, CPU-spike culprits, timeline chart |
| `wft/reliability.py` | Reads the System and Application logs with the built-in `wevtutil` tool, maps standard event IDs (1000, 1002, 41, 6008, 1001, 7031, 219, WHEA 17–19, disk 7/51/153) to categories, and scores each day |
| `tests/` | 12 pytest tests, including parsing of real-format Windows event XML |

### Reliability score

Each day starts at 10 and loses points per event, with serious events costing more:
blue screen −3, unexpected shutdown −2, hardware error −2, disk error −1.5, driver failure −1,
app crash −0.5, app hang −0.3 (never below 1). This mirrors the idea behind Windows Reliability Monitor.

## Run it (Windows)

```bash
pip install -r requirements.txt

python wft_cli.py collect --minutes 120     # leave it running while you use the laptop normally
python wft_cli.py perf                       # performance + battery report
python wft_cli.py reliability --days 30      # crash / hang / shutdown report from event logs
```

No Windows machine or no time to collect? Try it on realistic sample data:

```bash
python wft_cli.py demo
```

Reports are written to `reports/`:
`performance_report.md`, `performance_timeline.png`, `reliability_report.md`, `reliability_events.csv`.

## My results

_Fill in after running on your own laptop, for example:_
- Collected **X samples over Y hours**; CPU P95 was **Z%**
- Battery drained **A% per hour** on battery; **B** caused **C%** of CPU spikes
- Found **N** reliability events in 30 days; **App** crashed most; average score **S / 10**

## Tech

Python · psutil · pandas · matplotlib · Windows Event Logs (wevtutil, XML) · pytest
