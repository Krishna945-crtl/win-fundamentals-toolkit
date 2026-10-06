"""Telemetry collector – samples system + per-process health every few seconds.

Writes two CSV files:
  system.csv     one row per sample: cpu, memory, disk, battery, plugged in or not
  processes.csv  top N processes by CPU for every sample
"""

import csv
import time
from datetime import datetime
from pathlib import Path

import psutil

SYSTEM_COLS = ["ts", "cpu_pct", "mem_pct", "disk_read_mb", "disk_write_mb", "battery_pct", "plugged"]
PROC_COLS = ["ts", "name", "cpu_pct", "mem_mb"]


def _battery():
    b = psutil.sensors_battery()  # None on desktops / VMs
    if b is None:
        return "", ""
    return round(b.percent, 1), int(bool(b.power_plugged))


def _top_processes(n, cores):
    rows = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        info = p.info
        if not info["name"] or info["name"] == "System Idle Process" or info["memory_info"] is None:
            continue
        # psutil gives % of ONE core, so 200% means two full cores – scale to whole machine
        cpu = (info["cpu_percent"] or 0.0) / cores
        rows.append((info["name"], round(cpu, 2), round(info["memory_info"].rss / 2**20, 1)))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:n]


def collect(out_dir="data", interval=5.0, duration_min=60.0, top_n=5):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sys_path, proc_path = out / "system.csv", out / "processes.csv"
    new_sys, new_proc = not sys_path.exists(), not proc_path.exists()
    cores = psutil.cpu_count() or 1

    # first cpu_percent() call always returns 0, so prime it once
    psutil.cpu_percent(None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    last_io = psutil.disk_io_counters()

    end = time.time() + duration_min * 60
    samples = 0
    with open(sys_path, "a", newline="") as fs, open(proc_path, "a", newline="") as fp:
        ws, wp = csv.writer(fs), csv.writer(fp)
        if new_sys:
            ws.writerow(SYSTEM_COLS)
        if new_proc:
            wp.writerow(PROC_COLS)

        while time.time() < end:
            time.sleep(interval)
            ts = datetime.now().isoformat(timespec="seconds")

            io = psutil.disk_io_counters()
            read_mb = (io.read_bytes - last_io.read_bytes) / 2**20 if io and last_io else 0
            write_mb = (io.write_bytes - last_io.write_bytes) / 2**20 if io and last_io else 0
            last_io = io

            batt, plugged = _battery()
            ws.writerow([ts, psutil.cpu_percent(None), psutil.virtual_memory().percent,
                         round(read_mb, 2), round(write_mb, 2), batt, plugged])
            for name, cpu, mem in _top_processes(top_n, cores):
                wp.writerow([ts, name, cpu, mem])

            fs.flush()
            fp.flush()
            samples += 1
            print(f"\r{samples} samples collected (Ctrl+C to stop)", end="", flush=True)

    print(f"\nSaved {samples} samples to {out.resolve()}")
    return samples
