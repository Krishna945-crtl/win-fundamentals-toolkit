import pandas as pd

from wft import demo
from wft.perf_report import battery_drain_per_hour, build_report, high_cpu_culprits, percentiles


def frame(rows):
    return pd.DataFrame(rows, columns=["ts", "cpu_pct", "mem_pct", "disk_read_mb", "disk_write_mb",
                                       "battery_pct", "plugged"]).assign(ts=lambda d: pd.to_datetime(d["ts"]))


def test_percentiles():
    p = percentiles(pd.Series(range(1, 101)))
    assert p["p50"] == 50.5 and p["p95"] == 95.0 and p["max"] == 100


def test_battery_drain_only_counts_unplugged_time():
    df = frame([
        ["2026-10-05 10:00", 20, 50, 0, 0, 90, 0],
        ["2026-10-05 11:00", 20, 50, 0, 0, 80, 0],   # -10% in 1 hour on battery
        ["2026-10-05 11:05", 20, 50, 0, 0, 82, 1],   # charging – ignored
        ["2026-10-05 12:00", 20, 50, 0, 0, 95, 1],
    ])
    assert battery_drain_per_hour(df, max_gap_min=90) == 10.0


def test_battery_sessions_split_on_long_gaps():
    df = frame([
        ["2026-10-05 08:00", 20, 50, 0, 0, 100, 0],
        ["2026-10-05 09:00", 20, 50, 0, 0, 94, 0],   # -6 in 1h
        ["2026-10-05 20:00", 20, 50, 0, 0, 70, 0],   # laptop was asleep – new session
        ["2026-10-05 21:00", 20, 50, 0, 0, 62, 0],   # -8 in 1h
    ])
    assert battery_drain_per_hour(df, max_gap_min=90) == 7.0   # (6 + 8) / 2h, not counting the 11h gap


def test_no_battery_returns_none():
    df = frame([["2026-10-05 10:00", 20, 50, 0, 0, None, None]])
    assert battery_drain_per_hour(df) is None


def test_spike_culprit_is_top_process_during_spikes():
    sys_df = frame([["2026-10-05 10:00", 95, 50, 0, 0, 80, 0],
                    ["2026-10-05 10:01", 30, 50, 0, 0, 80, 0]])
    proc_df = pd.DataFrame({
        "ts": pd.to_datetime(["2026-10-05 10:00"] * 2 + ["2026-10-05 10:01"]),
        "name": ["MsMpEng.exe", "chrome.exe", "chrome.exe"],
        "cpu_pct": [60, 20, 25],
        "mem_mb": [200, 900, 900],
    })
    culprits = high_cpu_culprits(sys_df, proc_df)
    assert culprits.iloc[0]["name"] == "MsMpEng.exe"
    assert culprits.iloc[0]["share_pct"] == 100.0


def test_demo_end_to_end(tmp_path):
    data = demo.make_telemetry(out_dir=tmp_path / "data", hours=2)
    result = build_report(data, out_dir=tmp_path / "reports", charts=True)
    assert result["samples"] == 1440
    assert result["drain_per_hour"] > 0
    assert (tmp_path / "reports" / "performance_timeline.png").exists()
