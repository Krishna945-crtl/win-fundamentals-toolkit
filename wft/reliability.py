"""Reliability analyzer – reads Windows Event Logs and scores system stability.

Uses wevtutil, which is built into every Windows install, so no extra packages are needed.
Event IDs below are the standard ones Windows writes for crashes, hangs and shutdowns.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

# (log, event id, provider hint) -> category
EVENT_MAP = {
    ("Application", 1000): "App crash",
    ("Application", 1002): "App hang",
    ("Application", 1026): "App crash",          # .NET runtime crash
    ("System", 41): "Unexpected shutdown",        # Kernel-Power: rebooted without clean shutdown
    ("System", 6008): "Unexpected shutdown",
    ("System", 1001): "Blue screen (BSOD)",       # BugCheck
    ("System", 7031): "Service crash",
    ("System", 7034): "Service crash",
    ("System", 219): "Driver failure",            # driver failed to load
    ("System", 7026): "Driver failure",
    ("System", 7000): "Service failed to start",
    ("System", 17): "Hardware error (WHEA)",
    ("System", 18): "Hardware error (WHEA)",
    ("System", 19): "Hardware error (WHEA)",
    ("System", 7): "Disk error",
    ("System", 51): "Disk error",
    ("System", 153): "Disk error",
}

# Event IDs are only unique per provider: BTHUSB (Bluetooth) also writes IDs 17/18,
# and many apps log their own "1000". So each ID only counts when it comes from
# the provider Windows actually uses for it (matched as a lowercase substring).
EXPECTED_PROVIDER = {
    1000: ("application error",),
    1002: ("application hang",),
    1026: (".net runtime",),
    41: ("kernel-power",),
    6008: ("eventlog",),
    1001: ("bugcheck", "wer-systemerrorreporting"),
    7031: ("service control manager",),
    7034: ("service control manager",),
    7000: ("service control manager",),
    7026: ("service control manager",),
    219: ("kernel-pnp",),
    17: ("whea-logger",),
    18: ("whea-logger",),
    19: ("whea-logger",),
    7: ("disk", "stor", "nvme"),
    51: ("disk", "stor", "nvme"),
    153: ("disk", "stor", "nvme"),
}


def provider_matches(eid, provider):
    expected = EXPECTED_PROVIDER.get(eid)
    return expected is None or any(name in provider.lower() for name in expected)


# how much each kind of event hurts the daily score (Windows Reliability Monitor uses a similar idea)
PENALTY = {
    "Blue screen (BSOD)": 3.0,
    "Unexpected shutdown": 2.0,
    "Hardware error (WHEA)": 2.0,
    "Disk error": 1.5,
    "Driver failure": 1.0,
    "App crash": 0.5,
    "App hang": 0.3,
    "Service crash": 0.5,
    "Service failed to start": 0.3,
}


def fetch_events(log, max_events=2000):
    """Pull recent events from a Windows log as XML using wevtutil."""
    ids = sorted({eid for (lg, eid) in EVENT_MAP if lg == log})
    query = "*[System[(" + " or ".join(f"EventID={i}" for i in ids) + ")]]"
    result = subprocess.run(
        ["wevtutil", "qe", log, f"/q:{query}", "/f:xml", f"/c:{max_events}", "/rd:true"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "wevtutil failed – run this on Windows")
    return result.stdout


def parse_events(xml_text, log):
    """Turn wevtutil XML output into a DataFrame of categorised events."""
    root = ET.fromstring(f"<Events>{xml_text}</Events>")
    rows = []
    for ev in root.findall("e:Event", NS):
        sysnode = ev.find("e:System", NS)
        eid = int(sysnode.find("e:EventID", NS).text)
        category = EVENT_MAP.get((log, eid))
        if not category:
            continue
        provider = sysnode.find("e:Provider", NS).get("Name", "")
        if not provider_matches(eid, provider):
            continue                              # same ID, different provider -> not a reliability event
        when = sysnode.find("e:TimeCreated", NS).get("SystemTime")

        # for app crashes/hangs the first data field is the program name, e.g. chrome.exe
        data = [d.text for d in ev.findall("e:EventData/e:Data", NS) if d.text]
        source = data[0] if category in ("App crash", "App hang") and data else provider

        rows.append({"time": when, "log": log, "event_id": eid, "category": category,
                     "source": source, "provider": provider})

    df = pd.DataFrame(rows, columns=["time", "log", "event_id", "category", "source", "provider"])
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601").dt.tz_convert(None)
    return df


def load_windows_events(max_events=2000):
    frames = [parse_events(fetch_events(log, max_events), log) for log in ("System", "Application")]
    return pd.concat(frames, ignore_index=True)


# the same program failing again on the same day is one problem, not many,
# so a single noisy app/service can cost at most this many "hits" per day
MAX_REPEATS_PER_DAY = 2


def daily_scores(df, days=None, max_repeats=MAX_REPEATS_PER_DAY):
    """Score each day out of 10: start at 10, subtract penalties, never below 1.

    Repeats of the same (source, category) on one day are capped at max_repeats,
    so one crash-looping service shows up as a problem without hiding everything else.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "events", "score"])
    d = df.assign(date=df["time"].dt.date)
    grouped = d.groupby(["date", "source", "category"]).size().reset_index(name="count")
    grouped["penalty"] = (grouped["category"].map(PENALTY).fillna(0.2)
                          * grouped["count"].clip(upper=max_repeats))
    per_day = grouped.groupby("date").agg(events=("count", "sum"), penalty=("penalty", "sum")).reset_index()
    if days:
        full = pd.DataFrame({"date": pd.date_range(end=d["time"].max().normalize(), periods=days).date})
        per_day = full.merge(per_day, on="date", how="left").fillna({"events": 0, "penalty": 0})
    per_day["score"] = (10 - per_day["penalty"]).clip(lower=1).round(1)
    return per_day[["date", "events", "score"]]


def repeat_offenders(df, min_events=10):
    """Programs/services that fail again and again – usually one fixable root cause."""
    if df.empty:
        return pd.DataFrame(columns=["source", "category", "events", "days_affected", "per_day"])
    d = df.assign(date=df["time"].dt.date)
    g = d.groupby(["source", "category"]).agg(events=("date", "size"), days_affected=("date", "nunique")).reset_index()
    g = g[g["events"] >= min_events]
    g["per_day"] = (g["events"] / g["days_affected"]).round(1)
    return g.sort_values("events", ascending=False).reset_index(drop=True)


def build_report(df, out_dir="reports", days=30):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not df.empty:
        cutoff = df["time"].max() - pd.Timedelta(days=days)
        df = df[df["time"] >= cutoff]

    scores = daily_scores(df, days=days) if not df.empty else daily_scores(df)
    by_cat = df["category"].value_counts().rename_axis("category").reset_index(name="count")
    crashers = (df[df["category"].isin(["App crash", "App hang"])]
                .groupby(["source", "category"]).size().reset_index(name="count")
                .sort_values("count", ascending=False).head(8))
    offenders = repeat_offenders(df)
    avg_score = round(scores["score"].mean(), 1) if not scores.empty else 10.0
    worst = scores.sort_values("score").head(3) if not scores.empty else scores

    lines = [
        "# Windows Reliability Report",
        "",
        f"Window: last **{days} days** | Events found: **{len(df)}** | Average reliability score: **{avg_score} / 10**",
        "",
        "## Repeat offenders (one root cause, many events)",
        "",
        (offenders.to_markdown(index=False)
         + "\n\nThese fail again and again. Updating or reinstalling the app or its driver usually fixes all of them at once."
         if not offenders.empty else "No program failed 10 or more times."),
        "",
        "## Problems by type",
        "",
        by_cat.to_markdown(index=False) if not by_cat.empty else "No reliability problems found.",
        "",
        "## Apps that crash or hang most",
        "",
        crashers.to_markdown(index=False) if not crashers.empty else "No app crashes or hangs.",
        "",
        "## Worst days",
        "",
        worst.to_markdown(index=False) if not worst.empty else "-",
    ]
    (out / "reliability_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    df.to_csv(out / "reliability_events.csv", index=False)
    return {"events": len(df), "avg_score": avg_score,
            "top_crasher": None if crashers.empty else crashers.iloc[0]["source"],
            "top_repeat_offender": None if offenders.empty else offenders.iloc[0]["source"]}
