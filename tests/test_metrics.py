"""Unit tests for the pure metrics aggregation module."""

import unittest
from datetime import datetime, timedelta

from trmnl_server.metrics import (
    ServeEvent,
    aggregate_metrics,
    voltage_to_percent,
    WINDOW_DAYS,
    _LIPO_CURVE,
)


def ts_for(d: datetime) -> float:
    """Local-time epoch for a datetime (matches aggregate's fromtimestamp)."""
    return d.timestamp()


class TestVoltageToPercent(unittest.TestCase):
    """Battery percent follows a LiPo discharge curve, 3.0V = 0% to 4.2V = 100%."""

    CURVE = [
        (3.00, 0), (3.10, 2), (3.20, 5), (3.30, 10), (3.42, 20), (3.53, 30),
        (3.63, 40), (3.72, 50), (3.80, 60), (3.89, 70), (3.99, 80), (4.05, 90),
        (4.20, 100),
    ]

    def test_every_table_point_returns_its_percent(self):
        """A reading exactly on a curve point returns that point's percent."""
        for volts, pct in self.CURVE:
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), pct)

    def test_interpolates_between_points(self):
        """Values between points are interpolated linearly and rounded."""
        for volts, pct in ((3.7, 48), (3.35, 14), (3.76, 55), (3.05, 1), (4.1, 93)):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), pct)

    def test_at_or_below_three_volts_is_zero(self):
        """3.0V is empty; lower readings that pass validation (down to 2.4V) clamp to 0."""
        for volts in (3.0, 2.9, 2.4, 2.0):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), 0)

    def test_at_or_above_four_point_two_is_hundred(self):
        """4.2V and above is full."""
        for volts in (4.2, 4.3, 4.5):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), 100)

    def test_percent_never_falls_as_voltage_rises(self):
        """Sweeping 2.40V to 4.30V in 0.01V steps never decreases and stays in 0..100."""
        previous = 0
        for step in range(240, 431):
            pct = voltage_to_percent(step / 100)
            self.assertGreaterEqual(pct, previous, f"dropped at {step / 100}V")
            self.assertTrue(0 <= pct <= 100)
            previous = pct

    def test_curve_constant_matches_spec_and_is_strictly_ascending(self):
        """bisect needs strictly ascending voltages; the points are the spec's table."""
        self.assertEqual(list(_LIPO_CURVE), self.CURVE)
        volts = [v for v, _ in _LIPO_CURVE]
        self.assertEqual(volts, sorted(set(volts)))


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
