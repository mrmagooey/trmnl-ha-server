"""Unit tests for the pure metrics aggregation module."""

import unittest
from datetime import datetime, timedelta

from trmnl_server.metrics import (
    ServeEvent,
    aggregate_metrics,
    voltage_to_percent,
    WINDOW_DAYS,
)


def ts_for(d: datetime) -> float:
    """Local-time epoch for a datetime (matches aggregate's fromtimestamp)."""
    return d.timestamp()


class TestVoltageToPercent(unittest.TestCase):
    def test_minimum_is_zero(self):
        self.assertEqual(voltage_to_percent(2.4), 0)

    def test_maximum_is_hundred(self):
        self.assertEqual(voltage_to_percent(4.2), 100)

    def test_midpoint(self):
        self.assertEqual(voltage_to_percent(3.3), 50)

    def test_clamps_below_range(self):
        self.assertEqual(voltage_to_percent(2.0), 0)

    def test_clamps_above_range(self):
        self.assertEqual(voltage_to_percent(4.5), 100)

    def test_matches_legacy_inline_formula(self):
        # The exact formula previously inlined in components.py:1186.
        for v in (2.4, 2.9, 3.3, 3.7, 3.91, 4.2):
            expected = max(0, min(100, int(round(((v - 2.4) / (4.2 - 2.4)) * 100))))
            self.assertEqual(voltage_to_percent(v), expected)


class TestAggregateMetrics(unittest.TestCase):
    def setUp(self):
        # A fixed, tz-stable "now": noon today.
        self.now_dt = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.now = ts_for(self.now_dt)

    def test_empty_events(self):
        out = aggregate_metrics([], self.now)
        self.assertEqual(out["window_days"], WINDOW_DAYS)
        self.assertEqual(out["dashboards_served"]["total"], 0)
        self.assertEqual(out["dashboards_served"]["by_device"], {})
        self.assertEqual(out["battery"], {})

    def test_counts_total_and_by_device(self):
        events = [
            ServeEvent(self.now, "AA", "morning", 3.9),
            ServeEvent(self.now, "AA", "evening", 3.8),
            ServeEvent(self.now, "BB", "morning", None),
        ]
        out = aggregate_metrics(events, self.now)
        self.assertEqual(out["dashboards_served"]["total"], 3)
        self.assertEqual(out["dashboards_served"]["by_device"]["AA"]["count"], 2)
        self.assertEqual(out["dashboards_served"]["by_device"]["BB"]["count"], 1)

    def test_daily_has_seven_entries_oldest_first(self):
        events = [ServeEvent(self.now, "AA", "morning", 3.9)]
        daily = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"]
        self.assertEqual(len(daily), 7)
        dates = [d["date"] for d in daily]
        self.assertEqual(dates, sorted(dates))  # ascending = oldest first
        self.assertEqual(dates[-1], self.now_dt.date().isoformat())  # today last

    def test_latest_reading_per_day_wins(self):
        early = self.now_dt.replace(hour=8)
        late = self.now_dt.replace(hour=20)
        events = [
            ServeEvent(ts_for(early), "AA", "morning", 4.0),
            ServeEvent(ts_for(late), "AA", "evening", 3.5),
        ]
        today = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"][-1]
        self.assertEqual(today["voltage"], 3.5)  # the later reading
        self.assertEqual(today["percent"], voltage_to_percent(3.5))

    def test_day_with_no_reading_is_null_object(self):
        events = [ServeEvent(self.now, "AA", "morning", 3.9)]
        daily = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"]
        yesterday = daily[-2]
        self.assertEqual(yesterday["voltage"], None)
        self.assertEqual(yesterday["percent"], None)
        self.assertIn("date", yesterday)  # slot is an object, never null itself

    def test_device_with_serves_but_no_battery_appears_with_all_null(self):
        events = [ServeEvent(self.now, "BB", "morning", None)]
        out = aggregate_metrics(events, self.now)
        self.assertIn("BB", out["battery"])
        daily = out["battery"]["BB"]["daily"]
        self.assertEqual(len(daily), 7)
        self.assertTrue(all(d["voltage"] is None for d in daily))
        # Device key sets match between the two sections.
        self.assertEqual(
            set(out["dashboards_served"]["by_device"]),
            set(out["battery"]),
        )

    def test_events_older_than_window_excluded(self):
        old = ts_for(self.now_dt - timedelta(days=8))
        events = [
            ServeEvent(self.now, "AA", "morning", 3.9),
            ServeEvent(old, "AA", "morning", 3.9),
        ]
        out = aggregate_metrics(events, self.now)
        self.assertEqual(out["dashboards_served"]["total"], 1)

    def test_generated_at_has_no_microseconds(self):
        out = aggregate_metrics([], self.now)
        self.assertNotIn(".", out["generated_at"])  # microsecond stripped


if __name__ == "__main__":
    unittest.main()
