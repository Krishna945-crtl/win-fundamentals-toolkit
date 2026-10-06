"""Windows Fundamentals Toolkit – command line.

  python wft_cli.py collect --minutes 120        record telemetry (leave it running)
  python wft_cli.py perf                          performance + battery report from data/
  python wft_cli.py reliability --days 30         crash / hang / shutdown report from Windows Event Logs
  python wft_cli.py demo                          try both reports on realistic sample data
"""

import argparse
import json

from wft import demo, perf_report, reliability


def main():
    ap = argparse.ArgumentParser(description="Windows Fundamentals Toolkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="record device telemetry")
    c.add_argument("--minutes", type=float, default=60)
    c.add_argument("--interval", type=float, default=5)
    c.add_argument("--out", default="data")

    p = sub.add_parser("perf", help="performance + battery report")
    p.add_argument("--data", default="data")

    r = sub.add_parser("reliability", help="reliability report from Windows Event Logs")
    r.add_argument("--days", type=int, default=30)

    sub.add_parser("demo", help="run both reports on sample data")

    args = ap.parse_args()

    if args.cmd == "collect":
        from wft.collector import collect
        try:
            collect(args.out, args.interval, args.minutes)
        except KeyboardInterrupt:
            print("\nStopped. Data saved.")

    elif args.cmd == "perf":
        print(json.dumps(perf_report.build_report(args.data), indent=2, default=str))
        print("Report: reports/performance_report.md  |  Chart: reports/performance_timeline.png")

    elif args.cmd == "reliability":
        df = reliability.load_windows_events()
        print(json.dumps(reliability.build_report(df, days=args.days), indent=2, default=str))
        print("Report: reports/reliability_report.md")

    elif args.cmd == "demo":
        data = demo.make_telemetry()
        print("Performance:", json.dumps(perf_report.build_report(data), indent=2, default=str))
        print("Reliability:", json.dumps(reliability.build_report(demo.make_events()), indent=2, default=str))
        print("Reports written to reports/")


if __name__ == "__main__":
    main()
