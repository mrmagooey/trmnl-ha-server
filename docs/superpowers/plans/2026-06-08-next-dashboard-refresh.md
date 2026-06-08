# Wake at Next Scheduled Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When no schedule entry is visible now, return a `refresh_rate` equal to the seconds until the next entry becomes visible, so the device sleeps until the next scheduled dashboard opens instead of waking on a flat 600s timer.

**Architecture:** A pure helper `_seconds_until_next_visible` in `config.py` enumerates candidate transition datetimes (each entry's `start_time` + midnight, over an 8-day horizon) and validates each with the existing `is_schedule_entry_visible`, returning the seconds to the earliest validating candidate (or `None`). Wired into the no-visible branch of `_handle_api_display`, with the flat 600 as the `None` fallback.

**Tech Stack:** Python 3.12, stdlib `datetime`, pytest.

**Branch:** `next-dashboard-refresh` (work in an isolated worktree on this branch).

**Spec:** `docs/superpowers/specs/2026-06-08-next-dashboard-refresh-design.md`

**Baseline:** `155 passed`. **Test command (everywhere):**
```
uv run --with pytest --with pyyaml pytest -q
```

---

## File Structure

- `src/trmnl_server/config.py` — add `_seconds_until_next_visible` (beside `is_schedule_entry_visible`); add `time` to the datetime import.
- `src/trmnl_server/api.py` — wire it into the no-visible branch of `_handle_api_display`.
- `tests/test_config.py` — unit tests (parity sweep + targeted cases).
- `tests/test_api.py` — integration tests for the wiring.
- `README.md`, `AGENTS.md` — brief behavior note.

---

## Task 1: `_seconds_until_next_visible` helper + tests

**Files:**
- Modify: `src/trmnl_server/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, add `_seconds_until_next_visible` to the `from trmnl_server.config import (...)` block (it already imports `is_schedule_entry_visible`, `_coerce_time`, etc.; the file also already imports `datetime, timedelta`). Add `import random` near the top imports. Then add this oracle + generator helpers and test class at the end of the file (before the `if __name__ == '__main__':` guard):

```python
# --- Brute-force oracle for the parity sweep (test-only reference) ---
from trmnl_server.config import MIN_REFRESH_SECONDS, is_schedule_entry_visible as _vis

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _next_visible_probe(schedule, now, logger, horizon_days=8):
    """Minute-by-minute brute force: the correctness oracle for the helper."""
    now_minute = now.replace(second=0, microsecond=0)
    horizon_end = now_minute + timedelta(days=horizon_days)
    t = now_minute + timedelta(minutes=1)
    while t <= horizon_end:
        if any(_vis(e, t, logger) for e in schedule):
            return max(MIN_REFRESH_SECONDS, int((t - now_minute).total_seconds()))
        t += timedelta(minutes=1)
    return None


def _random_entry(rng):
    entry = {"dashboard": "d"}
    if rng.random() < 0.75:
        sh, eh = rng.randrange(24), rng.randrange(24)
        sm, em = rng.choice([0, 15, 30, 45]), rng.choice([0, 15, 30, 45])
        entry["start_time"] = f"{sh:02d}:{sm:02d}"
        entry["end_time"] = f"{eh:02d}:{em:02d}"
    if rng.random() < 0.6:
        if rng.random() < 0.5:
            entry["days_of_the_week"] = rng.choice(_DAY_NAMES)
        else:
            entry["days_of_the_week"] = f"{rng.choice(_DAY_NAMES)}-{rng.choice(_DAY_NAMES)}"
    return entry


class TestSecondsUntilNextVisible(unittest.TestCase):
    """Tests for _seconds_until_next_visible."""

    def setUp(self):
        self.logger = mock.Mock()

    def test_next_visible_later_today(self):
        # Monday 08:00, window 09:00-17:00 -> 1 hour.
        sched = [{"dashboard": "d", "start_time": "09:00", "end_time": "17:00",
                  "days_of_the_week": "Monday-Sunday"}]
        now = datetime(2025, 1, 6, 8, 0)  # Monday
        self.assertEqual(_seconds_until_next_visible(sched, now, self.logger), 3600)

    def test_next_visible_across_midnight(self):
        # Monday 09:00, window 07:00-08:00 (already passed today) -> Tuesday 07:00.
        sched = [{"dashboard": "d", "start_time": "07:00", "end_time": "08:00",
                  "days_of_the_week": "Monday-Sunday"}]
        now = datetime(2025, 1, 6, 9, 0)  # Monday
        self.assertEqual(_seconds_until_next_visible(sched, now, self.logger), 22 * 3600)

    def test_day_restricted_no_window_next_allowed_midnight(self):
        # Wednesday-only, no time window -> visible all day Wednesday, from 00:00.
        sched = [{"dashboard": "d", "days_of_the_week": "Wednesday"}]
        now = datetime(2025, 1, 6, 10, 0)  # Monday 10:00
        # Mon 10:00 -> Wed 00:00 = 1 day 14h = 38h.
        self.assertEqual(_seconds_until_next_visible(sched, now, self.logger), 38 * 3600)

    def test_overnight_window_with_weekday_restriction(self):
        # 22:00-06:00 Mon-Fri. Saturday midday -> next visible Monday 00:00
        # (post-midnight segment, Monday is allowed).
        sched = [{"dashboard": "d", "start_time": "22:00", "end_time": "06:00",
                  "days_of_the_week": "Monday-Friday"}]
        now = datetime(2025, 1, 11, 12, 0)  # Saturday 12:00
        # Sat 12:00 -> Mon 00:00 = 1 day 12h = 36h.
        self.assertEqual(_seconds_until_next_visible(sched, now, self.logger), 36 * 3600)

    def test_start_time_without_end_time_is_all_day(self):
        # start_time present but no end_time -> treated as all-day (matches
        # is_schedule_entry_visible), so visible from Wednesday 00:00, not 09:00.
        sched = [{"dashboard": "d", "start_time": "09:00", "days_of_the_week": "Wednesday"}]
        now = datetime(2025, 1, 6, 10, 0)  # Monday 10:00
        self.assertEqual(_seconds_until_next_visible(sched, now, self.logger), 38 * 3600)

    def test_never_visible_returns_none(self):
        # "Friday-Monday" wrap-range is never visible (preserved quirk).
        sched = [{"dashboard": "d", "days_of_the_week": "Friday-Monday"}]
        now = datetime(2025, 1, 6, 10, 0)
        self.assertIsNone(_seconds_until_next_visible(sched, now, self.logger))

    def test_empty_schedule_returns_none(self):
        now = datetime(2025, 1, 6, 10, 0)
        self.assertIsNone(_seconds_until_next_visible([], now, self.logger))

    def test_parity_with_minute_probe(self):
        # The candidate algorithm must match a brute-force minute probe for every
        # case where nothing is visible *now* (the function's actual domain).
        # A 2-day horizon keeps the O(minutes) oracle fast; the targeted tests
        # above cover the full 8-day weekly horizon.
        rng = random.Random(20260608)
        compared = 0
        base = datetime(2025, 1, 6, 0, 0)  # Monday 00:00
        for _ in range(80):
            sched = [_random_entry(rng) for _ in range(rng.randint(0, 3))]
            now = base + timedelta(minutes=rng.randrange(2 * 1440))
            if any(_vis(e, now, self.logger) for e in sched):
                continue  # outside the function's domain (something visible now)
            compared += 1
            self.assertEqual(
                _seconds_until_next_visible(sched, now, self.logger, horizon_days=2),
                _next_visible_probe(sched, now, self.logger, horizon_days=2),
                f"mismatch: now={now} schedule={sched}",
            )
        self.assertGreater(compared, 10, "parity sweep compared too few cases to be meaningful")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pytest --with pyyaml pytest tests/test_config.py::TestSecondsUntilNextVisible -q`
Expected: FAIL — `ImportError: cannot import name '_seconds_until_next_visible'`.

- [ ] **Step 3: Implement the helper**

In `src/trmnl_server/config.py`, change the datetime import:
```python
from datetime import datetime, timedelta
```
to:
```python
from datetime import datetime, timedelta, time
```
Then add this function at the **end** of the file (after `is_schedule_entry_visible`):
```python
def _seconds_until_next_visible(
    schedule: list[ScheduleEntry],
    now: datetime,
    logger: "Logger",
    horizon_days: int = 8,
) -> int | None:
    """Seconds until the next moment any schedule entry becomes visible.

    Used when no entry is visible now, to sleep the device until the next
    scheduled dashboard opens. Visibility can only turn on at an entry's
    ``start_time`` minute boundary or at midnight (day change / overnight wrap),
    so this enumerates those candidate datetimes over ``horizon_days`` and
    validates each with ``is_schedule_entry_visible`` (the single source of truth
    for visibility), returning the seconds to the earliest validating candidate,
    floored to ``MIN_REFRESH_SECONDS``. Returns None when nothing becomes visible
    within the horizon (empty or never-matching schedule), so the caller can fall
    back to its default.

    Args:
        schedule: The device's schedule entries.
        now: Current local time.
        logger: Logger passed through to is_schedule_entry_visible.
        horizon_days: How far ahead to look (8 covers a weekly schedule).

    Returns:
        Seconds until the next visible moment, or None if none within horizon.
    """
    if not schedule:
        return None

    now_minute = now.replace(second=0, microsecond=0)
    horizon_end = now_minute + timedelta(days=horizon_days)

    # Times-of-day at which visibility can turn on: midnight always, plus each
    # entry's start_time (only when it has a full start/end window, mirroring
    # is_schedule_entry_visible). Over-generation is harmless — non-matching
    # candidates are rejected by the validator below.
    candidate_times: set[time] = {time(0, 0)}
    for entry in schedule:
        start_str = entry.get('start_time')
        end_str = entry.get('end_time')
        if start_str and end_str:
            try:
                candidate_times.add(
                    datetime.strptime(_coerce_time(start_str), "%H:%M").time()
                )
            except ValueError:
                pass  # unparseable -> entry behaves all-day; only midnight applies

    # Enumerate candidate datetimes across the horizon, earliest first.
    candidates: list[datetime] = []
    day = now_minute.date()
    while datetime.combine(day, time(0, 0), tzinfo=now_minute.tzinfo) <= horizon_end:
        for tod in candidate_times:
            candidate = datetime.combine(day, tod, tzinfo=now_minute.tzinfo)
            if now_minute < candidate <= horizon_end:
                candidates.append(candidate)
        day += timedelta(days=1)
    candidates.sort()

    for candidate in candidates:
        if any(is_schedule_entry_visible(e, candidate, logger) for e in schedule):
            return max(MIN_REFRESH_SECONDS, int((candidate - now_minute).total_seconds()))
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest tests/test_config.py::TestSecondsUntilNextVisible -q`
Expected: 8 passed (7 targeted + 1 parity sweep).

- [ ] **Step 5: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `163 passed` (155 + 8).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/config.py tests/test_config.py
git commit -m "feat: Add _seconds_until_next_visible schedule lookahead

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire into the no-visible branch of `/api/display`

**Files:**
- Modify: `src/trmnl_server/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing integration tests**

In `tests/test_api.py`, add these two tests to the `TestAPISimple` class (the class with `create_handler` / `test_api_display_*`):
```python
    @mock.patch('trmnl_server.api._seconds_until_next_visible', return_value=4242)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=False)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_no_visible_sleeps_until_next(self, mock_read_config, _vis, mock_next):
        """When nothing is scheduled for now, refresh_rate is the time until the next entry."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [
                {'dashboard': 'morning', 'start_time': '07:00', 'end_time': '08:00'},
            ]}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        self.assertIn('no_dashboard_visible.png', response['image_url'])
        self.assertEqual(response['refresh_rate'], '4242')
        mock_next.assert_called_once()

    @mock.patch('trmnl_server.api._seconds_until_next_visible', return_value=None)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=False)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_no_visible_none_falls_back_to_default(self, mock_read_config, _vis, mock_next):
        """When nothing becomes visible within the horizon, fall back to the 600s default."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [
                {'dashboard': 'morning', 'start_time': '07:00', 'end_time': '08:00'},
            ]}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        self.assertIn('no_dashboard_visible.png', response['image_url'])
        self.assertEqual(response['refresh_rate'], '600')
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tests/test_api.py -k no_visible -q`
Expected: FAIL — `AttributeError: <module 'trmnl_server.api'> does not have the attribute '_seconds_until_next_visible'` (it isn't imported/used yet).

- [ ] **Step 3: Import the helper**

In `src/trmnl_server/api.py`, the config import is currently:
```python
from .config import read_config, is_schedule_entry_visible, find_device, _coerce_time, _aligned_refresh_rate
```
Change it to add `_seconds_until_next_visible`:
```python
from .config import read_config, is_schedule_entry_visible, find_device, _coerce_time, _aligned_refresh_rate, _seconds_until_next_visible
```

- [ ] **Step 4: Add the `else` branch**

In `_handle_api_display`, the `if visible_entries:` block currently ends with the grid-alignment line and there is **no `else`**. The block looks like:
```python
                    refresh_rate = _aligned_refresh_rate(now, entry.get('start_time'), effective_rate)

                sleep_start_str: str | None = device_config.get('sleep_start')
```
Insert an `else` between them so it reads:
```python
                    refresh_rate = _aligned_refresh_rate(now, entry.get('start_time'), effective_rate)
                else:
                    # No dashboard scheduled for now: sleep until the next one opens
                    # (uncapped), falling back to the default if none is upcoming.
                    next_visible = _seconds_until_next_visible(schedule, now, self.logger)
                    if next_visible is not None:
                        refresh_rate = next_visible

                sleep_start_str: str | None = device_config.get('sleep_start')
```
(The `else` is attached to `if visible_entries:`; `schedule` and `now` are already in scope. The sleep-mode block below still runs and overrides when sleeping.)

- [ ] **Step 5: Run the integration tests, then the full suite**

Run: `uv run --with pytest --with pyyaml pytest tests/test_api.py -k no_visible -q`
Expected: 2 passed.

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `165 passed` (163 + 2).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/api.py tests/test_api.py
git commit -m "feat: Sleep until the next scheduled dashboard when none is visible

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Document the behavior

**Files:**
- Modify: `README.md`, `AGENTS.md`

- [ ] **Step 1: Note it in README.md**

In `README.md`, near where the schedule / `refresh_rate` behavior is described (search for `refresh_rate` or the schedule docs), add a sentence. If there's a schedule/refresh section, add this line there; otherwise place it just after the component/schedule configuration docs:
```markdown
When no schedule entry is active for the current time, the device is told to sleep until the next entry's window opens (rather than polling on a fixed timer), so scheduled dashboards appear on time. If no entry will become active within about a week, it falls back to a 600-second refresh.
```

- [ ] **Step 2: Note it in AGENTS.md**

In `AGENTS.md`, near the other scheduling/behavior notes (e.g. the `history_graph`/`todo_list` notes added previously), add:
```markdown
- When no schedule entry is visible, `/api/display` returns the time until the next entry becomes visible (`_seconds_until_next_visible` in `config.py`), so the device sleeps until the next dashboard opens; it falls back to the 600s default if nothing is upcoming within ~8 days.
```

- [ ] **Step 3: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `165 passed` (unchanged — docs only).

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: Document next-dashboard sleep behavior

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Full suite:** `uv run --with pytest --with pyyaml pytest -q` → `165 passed`.
- [ ] **Parity holds:** the `test_parity_with_minute_probe` sweep passes (candidate algorithm matches the brute-force oracle).
- [ ] **Behavior smoke:**
  ```
  PYTHONPATH=src python3 -c "
  from datetime import datetime
  import logging
  from trmnl_server.config import _seconds_until_next_visible
  sched = [{'dashboard':'d','start_time':'09:00','end_time':'17:00','days_of_the_week':'Monday-Sunday'}]
  print('secs to 09:00 from Mon 08:00:', _seconds_until_next_visible(sched, datetime(2025,1,6,8,0), logging.getLogger()))
  print('empty ->', _seconds_until_next_visible([], datetime(2025,1,6,8,0), logging.getLogger()))
  "
  ```
  Expected: `secs to 09:00 from Mon 08:00: 3600` and `empty -> None`.
- [ ] **Tree clean** after the three commits.

## Notes / Out of Scope

- No config flag (default behavior) and no max-gap cap (uncapped) — by decision.
- No change to `is_schedule_entry_visible` or the visible-entry (grid-aligned) refresh.
- The minute-probe lives only in the test file as the parity oracle.
