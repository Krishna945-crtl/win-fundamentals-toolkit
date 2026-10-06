"""Performance + battery analysis on the collected telemetry."""

from pathlib import Path

import pandas as pd


def load(data_dir):
    d = Path(data_dir)
    sys_df = pd.read_csv(d / "system.csv", parse_dates=["ts"])
    proc_df = pd.read_csv(d / "processes.csv", parse_dates=["ts"])
    return sys_df, proc_df


def percentiles(series):
    s = series.dropna()
    return {"p50": round(s.quantile(0.50), 1), "p95": round(s.quantile(0.95), 1), "max": round(s.max(), 1)}


def battery_drain_per_hour(sys_df, max_gap_min=10):
    """Average % battery lost per hour while running on battery (unplugged).

    A gap longer than max_gap_min (sleep, shutdown, charging break) starts a new session,
    so idle time between sessions is not counted as drain time.
    """
    b = sys_df.dropna(subset=["battery_pct"])
    b = b[b["plugged"] == 0].sort_values("ts")
    if len(b) < 2:
        return None

    b = b.assign(gap=b["ts"].diff().dt.total_seconds().fillna(0))
    b["session"] = (b["gap"] > max_gap_min * 60).cumsum()

    used, hours = 0.0, 0.0
    for _, s in b.groupby("session"):
        if len(s) < 2:
            continue
        used += max(s["battery_pct"].iloc[0] - s["battery_pct"].iloc[-1], 0)
        hours += (s["ts"].iloc[-1] - s["ts"].iloc[0]).total_seconds() / 3600
    return round(used / hours, 1) if hours > 0 else None


def high_cpu_culprits(sys_df, proc_df, threshold=80.0, top=5):
    """During samples where total CPU > threshold, which process was on top most often?"""
    spikes = sys_df.loc[sys_df["cpu_pct"] > threshold, "ts"]
    if spikes.empty:
        return pd.DataFrame(columns=["name", "spike_samples", "share_pct"])
    during = proc_df[proc_df["ts"].isin(spikes)]
    leaders = during.sort_values("cpu_pct", ascending=False).groupby("ts").head(1)
    counts = leaders["name"].value_counts().head(top)
    return pd.DataFrame({
        "name": counts.index,
        "spike_samples": counts.values,
        "share_pct": (counts.values / len(spikes) * 100).round(1),
    })


def top_consumers(proc_df, top=5):
    """Processes ranked by average CPU, with P95 CPU and average memory."""
    g = proc_df.groupby("name")
    out = pd.DataFrame({
        "avg_cpu": g["cpu_pct"].mean().round(2),
        "p95_cpu": g["cpu_pct"].quantile(0.95).round(2),
        "avg_mem_mb": g["mem_mb"].mean().round(0),
        "seen_in_samples": g.size(),
    })
    return out.sort_values("avg_cpu", ascending=False).head(top).reset_index()


def build_report(data_dir, out_dir="reports", charts=True):
    sys_df, proc_df = load(data_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    hours = (sys_df["ts"].max() - sys_df["ts"].min()).total_seconds() / 3600
    cpu, mem = percentiles(sys_df["cpu_pct"]), percentiles(sys_df["mem_pct"])
    drain = battery_drain_per_hour(sys_df)
    culprits = high_cpu_culprits(sys_df, proc_df)
    consumers = top_consumers(proc_df)

    lines = [
        "# Device Performance & Battery Report",
        "",
        f"Samples: **{len(sys_df):,}** over **{hours:.1f} hours**",
        "",
        "## System health",
        "",
        "| Metric | P50 | P95 | Max |",
        "|---|---|---|---|",
        f"| CPU % | {cpu['p50']} | {cpu['p95']} | {cpu['max']} |",
        f"| Memory % | {mem['p50']} | {mem['p95']} | {mem['max']} |",
        "",
        f"**Battery drain on battery power:** {f'{drain}% per hour' if drain is not None else 'not enough unplugged data'}",
        "",
        "## Top CPU consumers",
        "",
        consumers.to_markdown(index=False),
        "",
        "## Who caused CPU spikes (> 80%)",
        "",
        culprits.to_markdown(index=False) if not culprits.empty else "No CPU spikes above 80% recorded.",
    ]
    (out / "performance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if charts:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        ax[0].plot(sys_df["ts"], sys_df["cpu_pct"], lw=0.8, label="CPU %")
        ax[0].plot(sys_df["ts"], sys_df["mem_pct"], lw=0.8, label="Memory %")
        ax[0].set_ylabel("%")
        ax[0].legend(loc="upper right")
        ax[0].set_title("System load over time")
        b = sys_df.dropna(subset=["battery_pct"])
        ax[1].plot(b["ts"], b["battery_pct"], lw=1)
        ax[1].set_ylabel("Battery %")
        ax[1].set_title("Battery level")
        fig.tight_layout()
        fig.savefig(out / "performance_timeline.png", dpi=120)
        plt.close(fig)

    return {"samples": len(sys_df), "hours": round(hours, 1), "cpu": cpu, "mem": mem,
            "drain_per_hour": drain, "top_spike_process": None if culprits.empty else culprits.iloc[0].to_dict()}
