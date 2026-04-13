"""
Walk through two weeks in hourly increments, checking whether each
test practice's schedule would fire.

Run:  python -m tests.test_schedule_fire
"""

from datetime import datetime, timedelta

from praxis_core.dsl.triggers import Cadence, Schedule, should_schedule_fire


# -- Test schedules ----------------------------------------------------------

SCHEDULES = {
    "Leetcodes (weekdays@00:01)": Schedule(interval="weekdays", at="00:01"),
    "Call Akanksa (fri@17:00)": Schedule(interval="friday", at="17:00"),
    "Biweekly Shopping (2w tue, anchor 04-14)": Schedule(
        interval=Cadence(frequency="2w", beginning="2026-04-14", at="00:00"),
    ),
}

# Start: Monday 2026-04-13 00:00  (one day before the biweekly anchor)
START = datetime(2026, 4, 13, 0, 0)
HOURS = 24 * 21  # three full weeks


# -- Simulation --------------------------------------------------------------

def main():
    # Track last_fired per schedule (None = never fired)
    last_fired: dict[str, datetime | None] = {name: None for name in SCHEDULES}

    col_w = max(len(n) for n in SCHEDULES) + 2
    header = f"{'Datetime':<18}" + "".join(f"{n:<{col_w}}" for n in SCHEDULES)
    print(header)
    print("-" * len(header))

    for h in range(HOURS):
        now = START + timedelta(hours=h)
        fires = {}

        for name, sched in SCHEDULES.items():
            result = should_schedule_fire(sched, now, last_fired[name])
            fires[name] = result
            if result:
                last_fired[name] = now

        # Only print hours where at least one schedule fires
        if any(fires.values()):
            row = f"{now.strftime('%a %m-%d %H:%M'):<18}"
            for name in SCHEDULES:
                label = "FIRE" if fires[name] else "-"
                row += f"{label:<{col_w}}"
            print(row)


if __name__ == "__main__":
    main()
