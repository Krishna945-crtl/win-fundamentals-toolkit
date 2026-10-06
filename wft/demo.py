"""Realistic sample data so the reports can be tried without collecting for hours."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

APPS = {  # name: (typical cpu %, memory MB)
    "chrome.exe": (9, 1400), "Code.exe": (4, 650), "Teams.exe": (6, 800),
    "MsMpEng.exe": (3, 250), "explorer.exe": (1, 120), "python.exe": (5, 180),
    "SearchIndexer.exe": (2, 90), "OneDrive.exe": (1, 140),
}


def make_telemetry(out_dir="demo_data", hours=8, interval=5, seed=7):
    rnd = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 10, 5, 9, 0, 0)
    n = int(hours * 3600 / interval)

    battery, plugged = 100.0, 0
    sys_rows, proc_rows = [], []
    for i in range(n):
        ts = start + timedelta(seconds=i * interval)
        # a Defender scan and a Chrome-heavy afternoon create realistic spikes
        scan = 1500 <= i < 1700
        heavy = 3200 <= i < 3900
        if i == int(n * 0.6):
            plugged = 1
        load = {}
        for app, (cpu, mem) in APPS.items():
            c = max(0, rnd.gauss(cpu, cpu * 0.4))
            if app == "MsMpEng.exe" and scan:
                c += 55
            if app == "chrome.exe" and heavy:
                c += 45
            load[app] = (round(c, 2), round(mem * rnd.uniform(0.9, 1.15), 1))
        total = min(100, sum(c for c, _ in load.values()) + rnd.gauss(4, 2))
        drain = (0.0035 + total / 100 * 0.012) * interval / 5
        battery = min(100.0, battery + 0.02) if plugged else max(5.0, battery - drain)
        sys_rows.append([ts.isoformat(), round(total, 1), round(rnd.gauss(62, 6), 1),
                         round(abs(rnd.gauss(1.5, 1)), 2), round(abs(rnd.gauss(0.8, 0.6)), 2),
                         round(battery, 1), plugged])
        for app, (c, m) in sorted(load.items(), key=lambda kv: kv[1][0], reverse=True)[:5]:
            proc_rows.append([ts.isoformat(), app, c, m])

    pd.DataFrame(sys_rows, columns=["ts", "cpu_pct", "mem_pct", "disk_read_mb", "disk_write_mb",
                                    "battery_pct", "plugged"]).to_csv(out / "system.csv", index=False)
    pd.DataFrame(proc_rows, columns=["ts", "name", "cpu_pct", "mem_mb"]).to_csv(out / "processes.csv", index=False)
    return out


def make_events(days=30, seed=11):
    rnd = random.Random(seed)
    end = datetime(2026, 10, 5, 22, 0, 0)
    pool = [
        ("Application", 1000, "App crash", "Teams.exe", 9),
        ("Application", 1002, "App hang", "chrome.exe", 7),
        ("Application", 1000, "App crash", "Discord.exe", 4),
        ("Application", 1002, "App hang", "explorer.exe", 3),
        ("System", 41, "Unexpected shutdown", "Microsoft-Windows-Kernel-Power", 2),
        ("System", 7031, "Service crash", "Service Control Manager", 3),
        ("System", 219, "Driver failure", "Microsoft-Windows-Kernel-PnP", 2),
        ("System", 153, "Disk error", "disk", 1),
    ]
    rows = []
    for log, eid, cat, src, count in pool:
        for _ in range(count):
            t = end - timedelta(days=rnd.uniform(0, days), hours=rnd.uniform(0, 12))
            rows.append({"time": t, "log": log, "event_id": eid, "category": cat, "source": src, "provider": src})
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
