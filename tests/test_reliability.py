from pathlib import Path

import pandas as pd

from wft.reliability import build_report, daily_scores, parse_events, repeat_offenders

FIX = Path(__file__).parent / "fixtures"


def load(name, log):
    return parse_events((FIX / name).read_text(encoding="utf-8"), log)


def test_parses_app_crashes_and_hangs_with_program_name():
    df = load("events_application.xml", "Application")
    assert len(df) == 3                      # event 999 is not a reliability event
    assert set(df["category"]) == {"App crash", "App hang"}
    assert (df["source"] == "Teams.exe").sum() == 2
    assert "chrome.exe" in df["source"].values


def test_parses_system_events_by_provider():
    df = load("events_system.xml", "System")
    assert list(df["category"]) == ["Unexpected shutdown", "Service crash", "Hardware error (WHEA)"]
    assert df.iloc[0]["source"] == "Microsoft-Windows-Kernel-Power"


def test_same_event_id_from_other_provider_is_ignored():
    df = load("events_system.xml", "System")
    assert "BTHUSB" not in df["source"].values            # Bluetooth ID 18 is not a WHEA error
    assert (df["source"] == "Microsoft-Windows-WHEA-Logger").sum() == 1


def test_daily_score_penalises_serious_events_more():
    df = pd.concat([load("events_application.xml", "Application"), load("events_system.xml", "System")])
    scores = daily_scores(df).set_index("date")["score"]
    oct4, oct5 = scores[pd.Timestamp("2026-10-04").date()], scores[pd.Timestamp("2026-10-05").date()]
    assert oct4 == 9.5                       # one app crash
    assert oct5 == 10 - (0.3 + 0.5 + 2.0 + 0.5)   # hang + crash + unexpected shutdown + service crash
    assert oct5 < oct4


def test_score_never_drops_below_one():
    many = pd.DataFrame({"time": [pd.Timestamp("2026-10-01 10:00")] * 10,
                         "category": ["Blue screen (BSOD)"] * 10,
                         "source": [f"driver{i}.sys" for i in range(10)]})
    assert daily_scores(many)["score"].iloc[0] == 1


def test_report_names_top_crasher(tmp_path):
    df = load("events_application.xml", "Application")
    result = build_report(df, out_dir=tmp_path, days=30)
    assert result["top_crasher"] == "Teams.exe"
    assert (tmp_path / "reliability_report.md").exists()


def test_empty_log_gives_perfect_score(tmp_path):
    empty = parse_events("", "System")
    assert build_report(empty, out_dir=tmp_path)["avg_score"] == 10.0


def crash_loop(n, source="SensorFusionService.exe", category="App crash"):
    return pd.DataFrame({"time": pd.date_range("2026-10-05 08:00", periods=n, freq="20min"),
                         "category": [category] * n, "source": [source] * n})


def test_one_crash_looping_service_cannot_sink_the_score():
    score = daily_scores(crash_loop(30))["score"].iloc[0]
    assert score == 10 - 0.5 * 2          # capped at 2 repeats, not 30 x 0.5


def test_different_problems_on_same_day_still_add_up():
    df = pd.concat([crash_loop(30), crash_loop(1, "explorer.exe", "App hang"),
                    crash_loop(1, "Microsoft-Windows-Kernel-Power", "Unexpected shutdown")])
    assert daily_scores(df)["score"].iloc[0] == 10 - (1.0 + 0.3 + 2.0)


def test_repeat_offenders_flags_crash_loops():
    df = pd.concat([crash_loop(30), crash_loop(3, "chrome.exe", "App hang")])
    off = repeat_offenders(df)
    assert list(off["source"]) == ["SensorFusionService.exe"]
    assert off.iloc[0]["events"] == 30
