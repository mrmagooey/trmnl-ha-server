# Wake at the Next Scheduled Dashboard — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)

## Goal

When a device polls `/api/display` and **no schedule entry is visible right now**,
return a `refresh_rate` equal to the seconds until the **next** entry becomes
visible, so the device sleeps until the next scheduled dashboard opens instead
of waking on a flat 10-minute timer and showing "no dashboard" for up to 10
minutes past the scheduled start.

## Problem (current behavior)

In `_handle_api_display` (`api.py`), when a known device has no visible schedule
entry, `out_filename` becomes `no_dashboard_visible.png` and `refresh_rate`
keeps the handler default `self.refresh_rate = 600`. So during a scheduling gap
the device polls every 10 minutes and can be up to ~10 minutes late picking up
the next dashboard.

## Decisions (locked via brainstorming)

- **Default behavior** — no config flag; the no-visible branch always uses the
  next-visible time.
- **Uncapped** — sleep the full gap, even hours or up to ~a week. Consistent
  with the existing sleep-mode path, which already returns large
  time-until-`sleep_end` values.
- **Algorithm:** candidate-transition-times, not a linear minute-probe.
- **Semantics source of truth:** reuse `is_schedule_entry_visible` for all
  visibility decisions — never re-derive day/time/overnight logic.
- **Fallback:** if nothing becomes visible within the horizon, keep `600`.

## Algorithm: `_seconds_until_next_visible`

```python
def _seconds_until_next_visible(
    schedule: list[ScheduleEntry],
    now: datetime,
    logger: "Logger",
    horizon_days: int = 8,
) -> int | None
```

**Insight:** visibility only *changes* at a finite set of moments — each entry's
`start_time` minute boundary, and **midnight** (`00:00`, which governs all-day
entries and the post-midnight portion of overnight windows). So enumerate those
candidates and validate each with the existing visibility function.

1. `now_minute = now.replace(second=0, microsecond=0)`.
2. **Generate candidate datetimes.** For each entry, for each day `d` from
   `now_minute.date()` through `now_minute + horizon_days`:
   - Always emit `datetime.combine(d, 00:00)`.
   - Emit `datetime.combine(d, start_time)` **only when both `start_time` and
     `end_time` are present** (mirrors `is_schedule_entry_visible`'s
     `if start_time_str and end_time_str` guard). Parse `start_time` via
     `_coerce_time` + `strptime`; on parse failure, emit only the `00:00`
     candidate for that entry.
   - Preserve `now`'s tzinfo on the combined datetime (the app uses naive local
     time via `datetime.now()`, so this is naive in practice; mirroring tzinfo
     keeps it correct if that ever changes).
   - Keep only candidates strictly `> now_minute` and `<= now_minute +
     horizon_days`.
3. **Pick earliest valid.** Sort candidates ascending. Return
   `int((c - now_minute).total_seconds())`, floored to `MIN_REFRESH_SECONDS`,
   for the first candidate `c` where
   `any(is_schedule_entry_visible(e, c, logger) for e in schedule)`. Validate
   against **all** entries at each candidate, not just the one that generated it.
4. If no candidate validates within the horizon, return `None`.

**Why over-generation is safe:** candidate generation only needs to *cover* every
possible transition point. Surplus candidates (e.g. a `00:00` for a same-day
window) are rejected by `is_schedule_entry_visible`, so semantics can never drift
from the real visibility rule — including the "Friday-Monday" wrap-range quirk
(which `is_schedule_entry_visible` treats as never-visible) and the overnight +
weekday interaction.

**Complexity:** O(E²·H) worst case (E entries, H horizon days) — ~800
visibility checks for 10 entries over 8 days, with early exit on the first hit.
Compare to ~1.15M for a minute-probe.

**Horizon:** 8 days covers any weekly `days_of_the_week` schedule (max gap ≤ 7
days) with a one-day buffer. Beyond that → `None` (degenerate/empty schedule).

## Wiring (`api.py`, `_handle_api_display`)

In the branch where the device is known but there are no `visible_entries`
(image stays `no_dashboard_visible.png`), after building `schedule`:

```python
next_visible = _seconds_until_next_visible(schedule, now, self.logger)
if next_visible is not None:
    refresh_rate = next_visible
# else: keep the existing 600 default
```

- The sleep-mode block stays **after** this and still overrides when the device
  is in its sleep window (it targets the absolute `sleep_end`).
- The visible-entry path is unchanged — it uses the grid-aligned entry
  `refresh_rate` from the prior drift fix.
- `now` is the same `now = datetime.now()` already computed for visibility.

## Edge cases

| Case | Behavior |
|------|----------|
| Empty / no schedule | No candidates → `None` → 600 |
| All entries currently invisible, none ever visible (e.g. all wrap-range) | `None` → 600 |
| Entry with `days_of_the_week` but no time window | Visible all day → next allowed **midnight** candidate |
| Overnight window (`start > end`) | Post-midnight segment validated against the *next day's* weekday via the `00:00` candidate |
| `start_time` without `end_time` (or invalid time) | Treated as all-day (only `00:00` candidates), matching `is_schedule_entry_visible` |
| Next boundary < 1 min away | Floored to `MIN_REFRESH_SECONDS` |
| Multiple entries | Earliest validating candidate wins |
| Device in sleep window | Sleep-mode override still wins (applied after) |

## Testing (three levels)

- **Unit (`test_config`):**
  - **Parity sweep** — a test-only brute-force minute-probe oracle
    (`is_schedule_entry_visible` stepped minute-by-minute from `now_minute` up to
    the horizon, returning the seconds to the first visible boundary or `None`)
    compared against `_seconds_until_next_visible` across many randomized
    schedules and `now` values; they must agree. The oracle applies the **same**
    `MIN_REFRESH_SECONDS` floor and `now`-to-minute truncation as the helper so
    the two are exactly comparable. This is the primary correctness guarantee.
    (Use a fixed RNG seed so the sweep is deterministic.)
  - Targeted cases: next-visible later today; across midnight; `days_of_the_week`
    single-day → next allowed midnight; day-range; overnight + weekday → next
    allowed Monday `00:00`; `start_time` without `end_time`; nothing-visible →
    `None`; imminent boundary → floored.
- **Integration (`test_api`):** the no-visible branch returns the computed
  next-visible value in the `/api/display` response; empty schedule → `600`;
  sleep-mode still overrides.
- **E2E:** `/api/display` handler test asserts the response `refresh_rate`
  reflects the next-visible computation.

## Out of scope

- No config flag (it's the default).
- No cap / max-gap setting (uncapped by decision).
- No change to the visible-entry refresh (already grid-aligned).
- No change to `is_schedule_entry_visible` semantics (including the wrap-range
  quirk) — this feature is built entirely on top of it.
