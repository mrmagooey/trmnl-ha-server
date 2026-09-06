"""Component rendering functions for e-ink displays.

This module contains all the rendering functions for different component types
(history graphs, entities, calendars, etc.).
"""

from datetime import datetime, timedelta
from io import BytesIO
from math import ceil, sqrt
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from .models import CalendarEvent, DashboardConfig, RenderData

if TYPE_CHECKING:
    from logging import Logger

# Constants
COMPONENT_TITLE_FONT_SIZE: int = 35
COMPONENT_SCALE: int = 2
# Panel titles are quantised to these sizes so that neighbouring panels land on
# the same rung instead of each shrinking to its own arbitrary fit.
TITLE_SIZE_LADDER: tuple[int, ...] = (35, 30, 26, 22, 18)
TITLE_PADDING: int = 20
TITLE_MAX_LINES: int = 2
# A wrap must gain at least this many ladder rungs for a row to spend the
# vertical space on a second title line.
TITLE_WRAP_MIN_GAIN: int = 1
TITLE_LINE_SPACING: int = 4
TITLE_BAND_GAP: int = 4
# A title band may not consume more than this share of its tile's height.
TITLE_BAND_MAX_PERCENT: int = 45
# Body text (entity-list rows, calendar events, todo items) is quantised to
# these sizes for the same reason titles are: every row in a panel lands on one
# rung instead of each row shrinking to its own arbitrary fit, which otherwise
# renders a single list at three or four different sizes.
BODY_SIZE_LADDER: tuple[int, ...] = (28, 24, 20, 18, 16)
TODO_HEADER_H: int = 50
TODO_ROW_H: int = 36
TODO_BOTTOM_PAD: int = 15
NOTO_FONT: str = str(Path(__file__).parent / "assets" / "NotoSans-Regular.ttf")

# Pillow picks its text-shaping engine at import time: it uses raqm/HarfBuzz if
# it can dlopen the system libfribidi, and its own basic layout otherwise.
# Pillow's wheels do not bundle libfribidi, so the engine depends on whatever
# happens to be installed on the host — present on GitHub's ubuntu-latest
# runners, absent from our shipped Docker image and from local dev. The two
# engines produce glyph widths that differ by a fraction of a percent, which is
# enough to flip a TITLE_SIZE_LADDER decision and change every rendered pixel.
# Force basic layout everywhere so rendering is reproducible. This app renders
# Latin text only; raqm's advantage is complex-script shaping (bidi, Arabic,
# Indic ligatures), which would need revisiting if that ever changes.
ImageFont.core.HAVE_RAQM = False
_font_warned: list[bool] = [False]  # logged once to avoid repetition per render


def _load_font(size: int, logger: "Logger") -> ImageFont.FreeTypeFont:
    """Load a font at the specified size.
    
    Args:
        size: Font size in points
        logger: Logger instance for warnings
        
    Returns:
        Loaded font object
    """
    try:
        return ImageFont.truetype(NOTO_FONT, size)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found, using default font. Check that the font file is present.", NOTO_FONT)
            _font_warned[0] = True
        return ImageFont.load_default()


def _incomplete_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Selects the todo items a panel actually displays.

    Args:
        items: Raw todo items, which may contain non-dict entries

    Returns:
        Items not marked completed, in their original order
    """
    return [
        it for it in items
        if isinstance(it, dict) and it.get('status', 'needs_action') != 'completed'
    ]


def _calendar_row_texts(events: list[CalendarEvent], logger: "Logger") -> list[str]:
    """Builds the one-line strings a calendar panel draws, in display order.

    Sorts `events` in place, as the draw function has always done. Shared with
    the row-level body-size resolver so the size is measured against exactly
    the strings that will be drawn.

    Args:
        events: Calendar events for the panel
        logger: Logger instance

    Returns:
        One formatted string per event
    """
    from datetime import date as dt_date
    from pprint import pformat as pf

    def get_sort_key(event: CalendarEvent) -> str:
        start = event.get('start', {})
        return start.get('dateTime') or start.get('date') or 'z'
    events.sort(key=get_sort_key)

    texts: list[str] = []
    for event in events:
        logger.debug("calendar event: %s", pf(event))
        summary: str = event.get('summary', 'No summary')
        start = event.get('start', {})
        end = event.get('end', {})

        start_date_time = start.get('dateTime')
        start_date = start.get('date')
        end_date_time = end.get('dateTime')
        if start_date_time:  # Timed event
            start_dt: datetime = datetime.fromisoformat(start_date_time).astimezone()
            end_dt: datetime = datetime.fromisoformat(end_date_time).astimezone() if end_date_time else start_dt
            day_name: str = start_dt.strftime('%A')
            texts.append(
                f"{day_name} {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}: {summary}"
            )
        elif start_date:  # All-day event
            start_date_obj = dt_date.fromisoformat(start_date)
            day_name = start_date_obj.strftime('%A')
            texts.append(f"{day_name} All day: {summary}")
        else:
            texts.append(f"Unknown: {summary}")
    return texts


def _entities_row_parts(
    entity_states: list[dict[str, str | float | None]],
) -> list[tuple[str, str]]:
    """Splits each entity-list row into its (name, ": state") halves.

    Kept as halves because the name is the part that gets truncated when a row
    will not fit; see _ellipsize_prefix.

    Args:
        entity_states: Entity state dictionaries for the panel

    Returns:
        One (name, tail) pair per entity, in display order
    """
    parts: list[tuple[str, str]] = []
    for entity in entity_states:
        name = str(entity.get('friendly_name', ''))  # type: ignore[arg-type]
        state: str | float | None = entity.get('state', 'N/A')
        state_str: str = f"{state:.2f}" if isinstance(state, float) else str(state)
        parts.append((name, f": {state_str}"))
    return parts


def _todo_row_texts(items: list[dict[str, str]]) -> list[str]:
    """Returns every incomplete todo summary, in list order.

    Deliberately not page-scoped: a paginating panel shows a different page on
    each refresh, and sizing per page would make the text jump between sizes as
    it cycles.

    Args:
        items: Raw todo items for the panel

    Returns:
        One summary string per incomplete item
    """
    return [item.get('summary', '') for item in _incomplete_items(items)]


def _panel_title_text(render_data: "RenderData") -> str:
    """Returns the title string a panel will actually draw.

    Todo panels append their incomplete count to the friendly name, so measuring
    the friendly name alone would under-measure them.

    Args:
        render_data: Component render data

    Returns:
        The title string, including any suffix the component adds
    """
    name: str = str(render_data.get('friendly_name', ''))
    if render_data.get('type') == 'todo_list':
        data = render_data.get('data')
        total: int = len(_incomplete_items(data)) if isinstance(data, list) else 0
        return f"{name} ({total})"
    return name


def _panel_draws_a_title(render_data: "RenderData") -> bool:
    """Returns whether the panel will draw a title, rather than a centred placeholder.

    Must agree with `_render_component`'s drawing decision: `data is None`
    always renders a titleless "No data for ..." placeholder, and a
    `history_graph` with an empty `data` list renders a titleless "No numeric
    data for ..." placeholder. Every other panel draws a title regardless of
    its data's content (e.g. an empty calendar still shows its title above
    "No upcoming events"), so it must still count toward the row minimum.

    Args:
        render_data: Component render data

    Returns:
        True if the panel will draw its title
    """
    data = render_data.get('data')
    if data is None:
        return False
    if render_data.get('type') == 'history_graph' and not data:
        return False
    return True


def _panel_body_fit(
    render_data: "RenderData",
    tile_width: int,
    logger: "Logger",
) -> int | None:
    """The body size a panel would pick for itself, or None if it draws no rows.

    The body-text counterpart of `_fit_title_size` at the panel level. Only the
    list-style panels have body rows to harmonise: `entity`/`url` draw a single
    value sized to fill the tile, and `history_graph` draws no body text at all.
    A panel whose data is empty (or absent) draws a fixed-size placeholder
    message instead of rows, so it must not drag its neighbours down.

    The widths below must match the content widths the draw functions compute,
    since the resolved size is what they will draw with.

    Args:
        render_data: Component render data
        tile_width: Unscaled width of the tile the panel will occupy
        logger: Logger instance

    Returns:
        A size from BODY_SIZE_LADDER, or None if the panel draws no body rows
    """
    data = render_data.get('data')
    if not data:
        return None

    panel_type = render_data.get('type')
    if panel_type == 'entities':
        texts = [name + tail for name, tail in _entities_row_parts(data)]  # type: ignore[arg-type]
        budget = (tile_width - 40) * COMPONENT_SCALE
    elif panel_type == 'calendar':
        texts = _calendar_row_texts(data, logger)  # type: ignore[arg-type]
        budget = (tile_width - 40) * COMPONENT_SCALE
    elif panel_type == 'todo_list':
        texts = _todo_row_texts(data)  # type: ignore[arg-type]
        cols = render_data.get('columns', 1)
        cols = cols if isinstance(cols, int) and cols > 0 else 1
        # Mirrors _draw_todo_list_component: checkbox inset + checkbox + gap,
        # then a trailing gap, inside one column of the tile.
        col_width = (tile_width * COMPONENT_SCALE) // cols
        budget = col_width - (15 + 24 + 8) * COMPONENT_SCALE - 8 * COMPONENT_SCALE
    else:
        return None

    if not texts:
        return None
    return _fit_body_size(texts, budget, logger)


def _fit_title_size(
    text: str,
    tile_width: int,
    logger: "Logger",
    *,
    lines: int = 1,
    max_band: int | None = None,
) -> int | None:
    """Picks the largest ladder rung whose title fits the given tile width.

    Runs before any canvas exists, so it measures with the font's own getbbox
    rather than ImageDraw.textbbox.

    Args:
        text: The title string that will be drawn
        tile_width: Unscaled width of the tile the title must fit
        logger: Logger instance
        lines: Maximum title lines to wrap onto
        max_band: Unscaled cap on the title band's height, or None for no cap

    Returns:
        A size from TITLE_SIZE_LADDER; the smallest rung if none fit. Returns
        None only when max_band is given and excludes every rung.
    """
    budget: int = (tile_width - TITLE_PADDING) * COMPONENT_SCALE
    for size in TITLE_SIZE_LADDER:
        if max_band is not None and _title_band_height(size, lines, logger) > max_band:
            continue
        font = _load_font(size * COMPONENT_SCALE, logger)
        wrapped = _wrap_title(text, font, budget, lines)
        if wrapped is None:
            continue
        if all(font.getbbox(line)[2] - font.getbbox(line)[0] <= budget for line in wrapped):
            return size

    if max_band is not None:
        # Every rung either overflowed the band cap or could not be wrapped.
        # Distinguish "cap excluded everything" from "nothing fitted the width".
        if all(
            _title_band_height(size, lines, logger) > max_band
            for size in TITLE_SIZE_LADDER
        ):
            return None
    return TITLE_SIZE_LADDER[-1]


def _fit_body_size(
    texts: list[str],
    max_width: int,
    logger: "Logger",
) -> int:
    """Picks the largest ladder rung at which every one of texts fits max_width.

    The body-text counterpart of _fit_title_size: one size is resolved for the
    whole group so a panel's rows share it, and it is quantised to a ladder so
    the sizes stay comparable rather than landing wherever each string's own
    shrink loop happened to stop.

    Args:
        texts: The strings that will be drawn, one per row
        max_width: Available width in SCALED pixels (unlike _fit_title_size,
            which takes an unscaled tile width, because every caller here
            already has a scaled content width to hand)
        logger: Logger instance

    Returns:
        An unscaled size from BODY_SIZE_LADDER; the smallest rung when no rung
        fits every text. Callers ellipsize the rows that still overflow there —
        one over-long row must not shrink the whole panel into illegibility.
    """
    for size in BODY_SIZE_LADDER:
        font = _load_font(size * COMPONENT_SCALE, logger)
        if all(font.getbbox(t)[2] - font.getbbox(t)[0] <= max_width for t in texts):
            return size
    return BODY_SIZE_LADDER[-1]


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int, d: "ImageDraw.ImageDraw") -> str:
    """Truncates text with a trailing ellipsis until it fits max_width.

    Args:
        text: The string that will be drawn
        font: The font it will be drawn with
        max_width: The available width, in the same units as textbbox
        d: A drawing context used only for text measurement

    Returns:
        text unchanged if it already fits within max_width; otherwise the
        longest prefix of text plus a trailing '…' that fits; '…' alone if
        even a single character plus the ellipsis does not fit.
    """
    bbox = d.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return text

    truncated: str = text
    while truncated:
        trunc_bbox = d.textbbox((0, 0), truncated + '…', font=font)
        if trunc_bbox[2] - trunc_bbox[0] <= max_width:
            break
        truncated = truncated[:-1]
    return (truncated + '…') if truncated else '…'


def _ellipsize_prefix(
    prefix: str,
    suffix: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    d: "ImageDraw.ImageDraw",
) -> str:
    """Ellipsizes prefix so that prefix + suffix fits max_width, keeping suffix.

    Entity-list rows read "<name>: <state>", and the state is the half worth
    reading. Plain _ellipsize eats a row from the right, which under a fixed
    body size would leave a truncated name and no value at all.

    Args:
        prefix: The part that may be truncated
        suffix: The part that must survive intact if at all possible
        font: The font the row will be drawn with
        max_width: Available width, in the same units as textbbox
        d: A drawing context used only for text measurement

    Returns:
        prefix + suffix unchanged when it already fits; otherwise a truncated
        prefix plus '…' plus the whole suffix. Falls back to truncating the
        joined string when the suffix alone does not fit.
    """
    joined: str = prefix + suffix
    bbox = d.textbbox((0, 0), joined, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return joined

    suffix_bbox = d.textbbox((0, 0), suffix, font=font)
    suffix_width: int = suffix_bbox[2] - suffix_bbox[0]
    if suffix_width >= max_width:
        return _ellipsize(joined, font, max_width, d)
    return _ellipsize(prefix, font, max_width - suffix_width, d) + suffix


def _wrap_title(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str] | None:
    """Wraps a title onto at most max_lines, breaking only at spaces.

    Measures with the font's own getbbox so it can run before any canvas
    exists. A single word wider than max_width is returned on its own line
    rather than broken; callers ellipsize such a line.

    Args:
        text: The title string
        font: Font the title will be drawn with
        max_width: Available width in the same (scaled) units as the font
        max_lines: Maximum number of lines permitted

    Returns:
        The wrapped lines, or None if the text needs more than max_lines
    """
    words: list[str] = text.split()
    if not words:
        return [text]

    lines: list[str] = []
    current: str = words[0]
    for word in words[1:]:
        candidate: str = current + " " + word
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)

    return lines if len(lines) <= max_lines else None


def _title_band_height(font_size: int, lines: int, logger: "Logger") -> int:
    """Height reserved below a title's anchor for the given line count.

    Measured through the same PIL routine the drawing functions paint with, so
    the reserved band and the painted extent cannot diverge. Uses a fixed
    "Ag" ascender/descender probe so the band does not vary with the glyphs of
    a particular title.

    Args:
        font_size: Unscaled title font size
        lines: Number of title lines
        logger: Logger instance

    Returns:
        Unscaled height from the title anchor to the bottom of its ink
    """
    font = _load_font(font_size * COMPONENT_SCALE, logger)
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    bbox = probe.multiline_textbbox(
        (0, 0),
        "\n".join(["Ag"] * max(1, lines)),
        font=font,
        spacing=TITLE_LINE_SPACING * COMPONENT_SCALE,
    )
    return bbox[3] // COMPONENT_SCALE


def _todo_header_height(title_font_size: int | None, title_lines: int, logger: "Logger") -> int:
    """Unscaled height of a todo panel's header band.

    One definition shared by _todo_capacity (which paginates before drawing)
    and _draw_todo_list_component (which draws). If these ever disagreed,
    pagination and rendering would diverge and rows would fall off the
    bottom of the panel.
    """
    if title_lines <= 1:
        return TODO_HEADER_H
    return max(
        TODO_HEADER_H,
        5 + _title_band_height(title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger) + TITLE_BAND_GAP,
    )


def _dashboard_rotation(dashboard: DashboardConfig) -> int | None:
    """Returns the rotation a dashboard asks for, or None for landscape."""
    rotate: int | None = dashboard.get('rotate')
    if rotate is None and dashboard.get('portrait'):
        rotate = 90
    return rotate


def _rotate_image(
    img: Image.Image,
    rotate: int | None,
    logger: "Logger",
) -> Image.Image:
    """Applies a configured rotation; unsupported values are logged and ignored.

    Used for every image served to a device — dashboards and the plain info
    placeholders alike — so a rotated device never gets one of them sideways.
    """
    if rotate in (90, -90, 180):
        return img.rotate(rotate, expand=True)
    if rotate is not None:
        logger.warning("Unsupported rotate value %r — must be 90, -90, or 180. Skipping rotation.", rotate)
    return img


def _create_info_image(
    message: str | None,
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Creates a PIL image with a centered message.
    
    Args:
        message: Message to display (can be multiline)
        width: Image width in pixels
        height: Image height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    img = Image.new('RGB', (width, height), color='white')
    d = ImageDraw.Draw(img)

    # Padding around the text block
    padding: int = 20
    max_text_width: int = max(1, width - 2 * padding)
    max_text_height: int = max(1, height - 2 * padding)

    # Choose a starting font size
    max_font_size: int = max(12, int(min(width, height) * 0.35))
    min_font_size: int = 12

    font = _load_font(max_font_size, logger)

    # Normalize message to string
    message_str: str = "" if message is None else str(message)

    def _measure(text: str, font_obj: ImageFont.FreeTypeFont) -> tuple[int, int]:
        bbox = d.multiline_textbbox((0, 0), text, font=font_obj, align='center')
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Shrink-to-fit loop
    font_size: int = max_font_size
    while font_size > min_font_size:
        font = _load_font(font_size, logger)
        text_w, text_h = _measure(message_str, font)
        if text_w <= max_text_width and text_h <= max_text_height:
            break
        font_size -= 2

    # Enforce minimum size
    if font_size < min_font_size:
        font_size = min_font_size
        font = _load_font(font_size, logger)

    text_w, text_h = _measure(message_str, font)
    x: float = (width - text_w) / 2
    y: float = (height - text_h) / 2

    d.multiline_text((x, y), message_str, font=font, fill='black', align='center')
    return img


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    fill: str,
    width: int,
    dash_on: int,
    dash_off: int,
) -> None:
    """Draw a dashed straight line between two points.

    PIL has no native dashed line, so we step along the segment drawing
    `dash_on`-long marks separated by `dash_off`-long gaps. A non-positive
    period (dash_on + dash_off) falls back to a solid line.

    Args:
        draw: Pillow ImageDraw to paint onto
        start: (x, y) start point
        end: (x, y) end point
        fill: line colour
        width: line width in pixels
        dash_on: painted dash length in pixels
        dash_off: gap length in pixels
    """
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    period = dash_on + dash_off
    if period <= 0:
        draw.line([start, end], fill=fill, width=width)
        return
    ux = dx / length
    uy = dy / length
    pos = 0.0
    while pos < length:
        seg = min(float(dash_on), length - pos)
        sx = x0 + ux * pos
        sy = y0 + uy * pos
        ex = x0 + ux * (pos + seg)
        ey = y0 + uy * (pos + seg)
        draw.line([(sx, sy), (ex, ey)], fill=fill, width=width)
        pos += period


def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float]],
    width: int,
    height: int,
    logger: "Logger",
    *,
    window_start: datetime,
    window_end: datetime,
    zero_baseline: bool = False,
    title_font_size: int | None = None,
    title_lines: int = 1,
) -> Image.Image:
    """Draws a single history graph component.

    Args:
        friendly_name: Display name for the component
        data_points: List of (timestamp, value) tuples
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        window_start: Start of the fixed time window (x-axis left bound).
        window_end: End of the fixed time window (x-axis right bound, typically "now").
        zero_baseline: When True, include 0 in the value range and draw a thin
            horizontal zero reference line with a labeled 0 y-tick.
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
        title_lines: Number of title lines to wrap onto. At 1 (the default)
            content starts at the legacy fixed offset unconditionally.

    Returns:
        Rendered PIL Image
    """
    # Create a larger image for antialiasing
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    # Load fonts
    try:
        padding: int = TITLE_PADDING * scale
        if title_font_size is not None:
            resolved_title_size: int = title_font_size * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        else:
            resolved_title_size = COMPONENT_TITLE_FONT_SIZE * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
            title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
            title_width_val: int = title_bbox[2] - title_bbox[0]

            while title_width_val > large_width - padding:
                resolved_title_size -= 2
                if resolved_title_size <= 8:
                    break
                font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
                title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
                title_width_val = title_bbox[2] - title_bbox[0]

        font_axes = ImageFont.truetype(NOTO_FONT, 15 * scale)
        font_value = ImageFont.truetype(NOTO_FONT, 30 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_axes = ImageFont.load_default()
        font_value = ImageFont.load_default()

    # Define graph dimensions
    # `margin` historically meant both the left inset and the top/bottom inset.
    # A wrapped title needs a taller top only, so the three are now distinct.
    margin_left: int = 40 * scale
    margin_bottom: int = 40 * scale
    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        margin_top: int = max(40 * scale, 2 * scale + band + TITLE_BAND_GAP * scale)
    else:
        margin_top = 40 * scale
    margin_right: int = ceil(margin_left * 1.6)
    graph_width: int = large_width - margin_left - margin_right
    graph_height: int = large_height - margin_top - margin_bottom - (10 * scale)

    # Handle no data case
    if not data_points:
        msg: str = f"No numeric data for {friendly_name}"
        text_bbox = d.textbbox((0, 0), msg, font=font_title)
        text_width: int = text_bbox[2] - text_bbox[0]
        text_height: int = text_bbox[3] - text_bbox[1]
        d.text(
            ((large_width - text_width) / 2, (large_height - text_height) / 2),
            msg,
            font=font_title,
            fill='black',
        )
        return img.resize((width, height), Image.LANCZOS)

    # Draw title
    if title_lines > 1:
        title_lines_text: list[str] = _wrap_title(
            friendly_name, font_title, large_width - padding, title_lines
        ) or [friendly_name]
    else:
        title_lines_text = [friendly_name]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - padding, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    text_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                     spacing=TITLE_LINE_SPACING * scale)
    text_width = text_bbox[2] - text_bbox[0]
    d.multiline_text(
        ((large_width - text_width) / 2, 2 * scale), rendered_title,
        font=font_title, fill='black', align='center',
        spacing=TITLE_LINE_SPACING * scale,
    )

    # Process data
    times: tuple[datetime, ...]
    values: tuple[float, ...]
    times, values = zip(*data_points)
    min_time: datetime = window_start
    max_time: datetime = window_end
    min_val: float = min(values)
    max_val: float = max(values)

    # Bipolar variant: anchor the range so 0 is always inside it.
    if zero_baseline:
        min_val = min(0.0, min_val)
        max_val = max(0.0, max_val)

    # Avoid division by zero
    if max_val == min_val:
        max_val += 1
        min_val -= 1

    time_delta: timedelta = max_time - min_time
    if time_delta.total_seconds() == 0:
        time_delta = timedelta(seconds=1)

    # Draw axes
    d.line(
        [(margin_left, margin_top), (margin_left, large_height - margin_bottom)],
        fill='black',
        width=scale * 2,
    )
    d.line(
        [(margin_left, large_height - margin_bottom), (large_width - margin_right, large_height - margin_bottom)],
        fill='black',
        width=scale * 2,
    )

    # Draw Y-axis labels
    num_y_labels: int = 3
    for i in range(num_y_labels + 1):
        val: float = min_val + (max_val - min_val) * i / num_y_labels
        y: float = (large_height - margin_bottom) - (i / num_y_labels) * graph_height
        if i == 0:
            y -= 10
        label: str = f"{val:.1f}"
        text_bbox = d.textbbox((0, 0), label, font=font_axes)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        d.text(
            (margin_left - text_width - (5 * scale), y - text_height / 2),
            label,
            font=font_axes,
            fill='black',
        )
        d.line([(margin_left - (5 * scale), y), (margin_left, y)], fill='black', width=scale)

    # Bipolar variant: guarantee a labeled "0" tick (unless one already lands on 0).
    if zero_baseline:
        existing_tick_vals = [
            min_val + (max_val - min_val) * i / num_y_labels
            for i in range(num_y_labels + 1)
        ]
        if not any(abs(v) < 1e-9 for v in existing_tick_vals):
            zero_y: float = (large_height - margin_bottom) - (
                (0.0 - min_val) / (max_val - min_val)
            ) * graph_height
            zlabel: str = "0.0"
            ztext_bbox = d.textbbox((0, 0), zlabel, font=font_axes)
            ztext_width: int = ztext_bbox[2] - ztext_bbox[0]
            ztext_height: int = ztext_bbox[3] - ztext_bbox[1]
            d.text(
                (margin_left - ztext_width - (5 * scale), zero_y - ztext_height / 2),
                zlabel,
                font=font_axes,
                fill='black',
            )
            d.line(
                [(margin_left - (5 * scale), zero_y), (margin_left, zero_y)],
                fill='black',
                width=scale,
            )

    # Draw X-axis labels
    if (max_time - min_time).total_seconds() > 0:
        num_x_labels: int = 4
        for i in range(num_x_labels + 1):
            time_point: datetime = min_time + (max_time - min_time) * i / num_x_labels
            x: float = margin_left + (i / num_x_labels) * graph_width
            label = time_point.astimezone().strftime("%H:%M")
            text_bbox = d.textbbox((0, 0), label, font=font_axes)
            text_width = text_bbox[2] - text_bbox[0]
            d.text(
                (x - text_width / 3, large_height - margin_bottom + (5 * scale)),
                label,
                font=font_axes,
                fill='black',
            )
            d.line(
                [(x, large_height - margin_bottom), (x, large_height - margin_bottom + (5 * scale))],
                fill='black',
                width=scale,
            )

    # Helper to convert data to pixel coordinates
    def to_coords(t: datetime, v: float) -> tuple[float, float]:
        x: float = margin_left + ((t - min_time) / time_delta) * graph_width
        x = max(float(margin_left), min(x, float(margin_left + graph_width)))
        y: float = (large_height - margin_bottom) - ((v - min_val) / (max_val - min_val)) * graph_height
        return x, y

    # Bipolar variant: thin horizontal reference line at value 0, spanning the
    # plot width. Thinner (width=scale) than the axes (scale * 2) and the data
    # line (4 * scale) so the visual hierarchy reads data > axes > zero line.
    if zero_baseline:
        _zx0, zero_line_y = to_coords(min_time, 0.0)
        d.line(
            [(margin_left, zero_line_y), (margin_left + graph_width, zero_line_y)],
            fill='black',
            width=scale,
        )

    # Display last value
    last_value: float = values[-1]
    last_value_text: str = f"{last_value:.1f}"
    _last_x, last_y = to_coords(times[-1], last_value)
    text_bbox = d.textbbox((0, 0), last_value_text, font=font_value)
    text_height = text_bbox[3] - text_bbox[1]
    text_x: float = large_width - margin_right + (5 * scale)
    text_y: float = last_y - (text_height / 2)
    d.text((text_x, text_y), last_value_text, font=font_value, fill='black')

    # Draw data line
    points_coords: list[tuple[float, float]] = [to_coords(t, v) for t, v in data_points]
    if len(points_coords) > 1:
        d.line(points_coords, fill='black', width=4 * scale)

    # Hold the last received value forward to the right edge (now) as a dotted line.
    last_point_x, last_point_y = to_coords(times[-1], last_value)
    right_edge_x, _ = to_coords(max_time, last_value)
    if right_edge_x > last_point_x:
        _draw_dashed_line(
            d,
            (last_point_x, last_point_y),
            (right_edge_x, last_point_y),
            fill='black',
            width=4 * scale,
            dash_on=12 * scale,
            dash_off=8 * scale,
        )

    return img.resize((width, height), Image.LANCZOS)


def _draw_entity_component(
    friendly_name: str,
    value: str | float | int | None,
    width: int,
    height: int,
    logger: "Logger",
    *,
    title_font_size: int | None = None,
    title_lines: int = 1,
) -> Image.Image:
    """Draws a single entity component.

    Args:
        friendly_name: Display name for the component
        value: Entity state value
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
        title_lines: Number of title lines to wrap onto. At 1 (the default)
            the value is centred in the whole tile unconditionally.

    Returns:
        Rendered PIL Image
    """
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    # Dynamically adjust title font size
    padding: int = TITLE_PADDING * scale
    font_title = ImageFont.load_default()
    try:
        if title_font_size is not None:
            resolved_title_size: int = title_font_size * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        else:
            resolved_title_size = COMPONENT_TITLE_FONT_SIZE * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
            title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
            title_width_val: int = title_bbox[2] - title_bbox[0]

            while title_width_val > large_width - padding:
                resolved_title_size -= 2
                if resolved_title_size <= 8:
                    break
                font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
                title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
                title_width_val = title_bbox[2] - title_bbox[0]
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True

    y_tweak: int = 40
    # Draw title
    if title_lines > 1:
        title_lines_text: list[str] = _wrap_title(
            friendly_name, font_title, large_width - padding, title_lines
        ) or [friendly_name]
    else:
        title_lines_text = [friendly_name]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - padding, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    title_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                       spacing=TITLE_LINE_SPACING * scale)
    title_width: int = title_bbox[2] - title_bbox[0]
    title_x: float = (large_width - title_width) / 2
    title_y: float = 20 * scale - y_tweak
    d.multiline_text(
        (title_x, title_y), rendered_title, font=font_title, fill='black',
        align='center', spacing=TITLE_LINE_SPACING * scale,
    )

    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        avail_top: int = band
    else:
        avail_top = 0
    avail_h: int = large_height - avail_top

    if value is None:
        value_str: str = "N/A"
    elif isinstance(value, float):
        value_str = f"{value:.2f}"
    else:
        value_str = str(value)

    # Adjust font size and wrap text
    font_size: int = 168 * scale
    min_font_size: int = 16 * scale
    font_value = ImageFont.load_default()
    try:
        font_value = ImageFont.truetype(NOTO_FONT, font_size)
        value_bbox = d.textbbox((0, 0), value_str, font=font_value)
        value_width: int = value_bbox[2] - value_bbox[0]

        while (
            value_width > large_width - padding
            # Use bbox[3] (anchor-to-ink-bottom), not ink-only height: once the
            # clamp below pins value_y to avail_top, the anchor IS the region's
            # top edge, so this must match _title_band_height's convention or
            # the ink can spill past avail_top + avail_h.
            or value_bbox[3] > avail_h
        ):
            font_size -= 4
            if font_size <= min_font_size:
                break
            font_value = ImageFont.truetype(NOTO_FONT, font_size)
            value_bbox = d.textbbox((0, 0), value_str, font=font_value)
            value_width = value_bbox[2] - value_bbox[0]

        # ponytail: this word-wrap duplicates _wrap_title's logic rather than
        # calling it, because the two aren't interchangeable: this measures
        # with ImageDraw.textbbox and a strict `<` against a live canvas,
        # while _wrap_title measures with font.getbbox and `<=` so the row
        # resolver can pick a size before any canvas exists. Unifying them
        # risks shifting existing value renders by a word for no benefit here.
        # Wrap text if still too wide
        if value_width > large_width - padding:
            lines: list[str] = []
            words: list[str] = value_str.split()
            if words:
                current_line: str = words[0]
                for word in words[1:]:
                    test_line: str = current_line + " " + word
                    bbox = d.textbbox((0, 0), test_line, font=font_value)
                    if bbox[2] - bbox[0] < large_width - padding:
                        current_line = test_line
                    else:
                        lines.append(current_line)
                        current_line = word
                lines.append(current_line)
            value_str = "\n".join(lines)

        # Word wrapping splits on spaces, so it cannot break a single long
        # token (a JSON blob, a hash, an id) — and a word longer than the tile
        # still overflows the line it lands on. Either way the line is centred
        # at a negative x and spills past both tile edges. Ellipsize any line
        # that still does not fit; _ellipsize returns a fitting line unchanged,
        # so values that already fit render identically.
        value_str = "\n".join(
            _ellipsize(line, font_value, large_width - padding, d)
            for line in value_str.split("\n")
        )

        # This cap only engages once the value has wrapped onto multiple
        # lines. A single-line value floored by min_font_size with
        # value_bbox[3] still > avail_h is not re-checked here — it relies on
        # TITLE_MAX_LINES == 2 and Task 6's TITLE_BAND_MAX_PERCENT cap on the
        # band, which together keep avail_h at least ~55% of tile height (a
        # smaller tile admits no rung and falls back to a full-height,
        # one-line title). Raising TITLE_MAX_LINES or loosening
        # TITLE_BAND_MAX_PERCENT would reopen this and need a height re-check.
        if '\n' in value_str:
            # PIL's text() uses spacing=4 ABSOLUTE for embedded newlines.
            # This "Ag" probe deliberately over-estimates the true per-line
            # advance, so the line cap below is conservative (undercounts
            # max_value_lines) rather than permissive.
            probe_bbox = d.multiline_textbbox((0, 0), "Ag", font=font_value, spacing=4)
            line_probe_height: int = max(1, probe_bbox[3])
            max_value_lines: int = max(1, avail_h // line_probe_height)
            wrapped_lines: list[str] = value_str.split('\n')
            if len(wrapped_lines) > max_value_lines:
                wrapped_lines = wrapped_lines[:max_value_lines]
                wrapped_lines[-1] = _ellipsize(
                    wrapped_lines[-1], font_value, large_width - padding, d
                )
                value_str = '\n'.join(wrapped_lines)
    except IOError:
        pass  # Use default font

    # Center value
    value_bbox = d.textbbox((0, 0), value_str, font=font_value)
    value_width = value_bbox[2] - value_bbox[0]
    value_height: int = value_bbox[3] - value_bbox[1]

    value_x: float = (large_width - value_width) / 2
    if title_lines > 1:
        # y_tweak below is a fixed offset tuned for the single-line path,
        # where the title overlaps the value's reserved region rather than
        # sitting in its own band. It doesn't scale with font size, so at
        # the large fonts a generous avail_h allows here it under-corrects
        # and pushes the ink past the tile's bottom edge. Centre the actual
        # ink box instead: value_bbox[1] is its offset from the anchor, so
        # the anchor may legitimately sit above avail_top by that much
        # without the ink itself entering the title band.
        value_y: float = avail_top + (avail_h - value_height) / 2 - value_bbox[1]
        min_value_y: float = avail_top - value_bbox[1]
    else:
        final_y_tweak: int = y_tweak if '\n' not in value_str else 0
        value_y = avail_top + (avail_h - value_height) / 2 - final_y_tweak
        min_value_y = float(avail_top)
    value_y = max(min_value_y, value_y)
    # Never let the ink extend past the bottom of the tile, whichever path
    # produced it — a floored font size or an off-tuned offset can otherwise
    # still push value_bbox[3] beyond avail_top + avail_h.
    value_y = min(value_y, max(min_value_y, float(avail_top + avail_h - value_bbox[3])))

    d.text((value_x, value_y), value_str, font=font_value, fill='black', align='center')

    return img.resize((width, height), Image.LANCZOS)


def _draw_calendar_component(
    friendly_name: str,
    events: list[CalendarEvent],
    width: int,
    height: int,
    logger: "Logger",
    *,
    title_font_size: int | None = None,
    title_lines: int = 1,
    body_font_size: int | None = None,
) -> Image.Image:
    """Draws a calendar component.

    Args:
        friendly_name: Display name for the component
        events: List of calendar events
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        body_font_size: Event-row size resolved by the caller so every panel in
            the layout row agrees. When None, this panel picks its own rung.
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
        title_lines: Number of title lines to wrap onto. At 1 (the default)
            content starts at the legacy fixed offset unconditionally.

    Returns:
        Rendered PIL Image
    """
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        resolved_title_size: int = (
            title_font_size if title_font_size is not None else COMPONENT_TITLE_FONT_SIZE
        ) * scale
        font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        font_event = ImageFont.truetype(NOTO_FONT, 28 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_event = ImageFont.load_default()

    # Draw title
    if title_lines > 1:
        title_lines_text: list[str] = _wrap_title(
            friendly_name, font_title, large_width - TITLE_PADDING * scale, title_lines
        ) or [friendly_name]
    else:
        title_lines_text = [friendly_name]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - TITLE_PADDING * scale, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    text_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                     spacing=TITLE_LINE_SPACING * scale)
    text_width: int = text_bbox[2] - text_bbox[0]
    d.multiline_text(
        ((large_width - text_width) / 2, 5 * scale), rendered_title,
        font=font_title, fill='black', align='center',
        spacing=TITLE_LINE_SPACING * scale,
    )

    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        y_pos: int = max(50 * scale, 5 * scale + band + TITLE_BAND_GAP * scale)
    else:
        y_pos = 50 * scale
    line_spacing: int = 8 * scale

    if not events:
        msg: str = "No upcoming events"
        text_bbox = d.textbbox((0, 0), msg, font=font_event)
        text_width = text_bbox[2] - text_bbox[0]
        d.text(((large_width - text_width) / 2, y_pos), msg, font=font_event, fill='black')
    else:
        event_strings: list[str] = _calendar_row_texts(events, logger)

        padding: int = 40 * scale
        content_width: int = large_width - padding

        # One size for every event in the panel, resolved before anything is
        # drawn, so a single long summary no longer renders at half the size of
        # the event above it. The caller may supply a size agreed across the
        # whole layout row instead.
        font_row = _load_font(
            (body_font_size if body_font_size is not None
             else _fit_body_size(event_strings, content_width, logger)) * scale,
            logger,
        )
        # A single shared row advance: even at one font size the per-row ink
        # height still swings with ascenders and descenders, which is what made
        # the old spacing ragged.
        row_probe = d.textbbox((0, 0), "Ag", font=font_row)
        row_advance: int = (row_probe[3] - row_probe[1]) + line_spacing

        for event_str in event_strings:
            # The ladder floor can still leave an event too wide — an
            # unbreakable summary. Rows are not wrapped, so truncate instead.
            # _ellipsize returns a fitting string unchanged.
            d.text(
                (20 * scale, y_pos),
                _ellipsize(event_str, font_row, content_width, d),
                font=font_row,
                fill='black',
            )
            y_pos += row_advance

            if y_pos > large_height - 30 * scale:
                break

    return img.resize((width, height), Image.LANCZOS)


def _draw_entities_component(
    friendly_name: str,
    entity_states: list[dict[str, str | float | None]],
    width: int,
    height: int,
    logger: "Logger",
    *,
    title_font_size: int | None = None,
    title_lines: int = 1,
    body_font_size: int | None = None,
) -> Image.Image:
    """Draws a list of entities and their states.

    Args:
        friendly_name: Display name for the component
        entity_states: List of entity state dictionaries
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        body_font_size: List-row size resolved by the caller so every panel in
            the layout row agrees. When None, this panel picks its own rung.
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
        title_lines: Number of title lines to wrap onto. At 1 (the default)
            content starts at the legacy fixed offset unconditionally.

    Returns:
        Rendered PIL Image
    """
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        resolved_title_size: int = (
            title_font_size if title_font_size is not None else COMPONENT_TITLE_FONT_SIZE
        ) * scale
        font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        font_list = ImageFont.truetype(NOTO_FONT, 28 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_list = ImageFont.load_default()

    # Draw title
    if title_lines > 1:
        title_lines_text: list[str] = _wrap_title(
            friendly_name, font_title, large_width - TITLE_PADDING * scale, title_lines
        ) or [friendly_name]
    else:
        title_lines_text = [friendly_name]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - TITLE_PADDING * scale, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    text_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                     spacing=TITLE_LINE_SPACING * scale)
    text_width: int = text_bbox[2] - text_bbox[0]
    d.multiline_text(
        ((large_width - text_width) / 2, 5 * scale), rendered_title,
        font=font_title, fill='black', align='center',
        spacing=TITLE_LINE_SPACING * scale,
    )

    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        y_pos: int = max(50 * scale, 5 * scale + band + TITLE_BAND_GAP * scale)
    else:
        y_pos = 50 * scale
    line_spacing: int = 8 * scale

    if not entity_states:
        msg: str = "No entities to display"
        text_bbox = d.textbbox((0, 0), msg, font=font_list)
        text_width = text_bbox[2] - text_bbox[0]
        d.text(((large_width - text_width) / 2, y_pos), msg, font=font_list, fill='black')
    else:
        padding: int = 40 * scale
        content_width: int = large_width - padding

        rows: list[tuple[str, str]] = _entities_row_parts(entity_states)

        # One size for the whole list, resolved before anything is drawn. The
        # caller may supply a size agreed across the whole layout row instead.
        font_row = _load_font(
            (body_font_size if body_font_size is not None else _fit_body_size(
                [name + tail for name, tail in rows], content_width, logger
            )) * scale,
            logger,
        )
        # A single shared row advance: even at one font size the per-row ink
        # height still swings with ascenders and descenders, which is what made
        # the old spacing ragged.
        row_probe = d.textbbox((0, 0), "Ag", font=font_row)
        row_advance: int = (row_probe[3] - row_probe[1]) + line_spacing

        for name, tail in rows:
            # The ladder floor can still leave a row too wide. Rows are not
            # wrapped, so truncate the name and keep the state visible;
            # _ellipsize_prefix returns a fitting row unchanged.
            d.text(
                (20 * scale, y_pos),
                _ellipsize_prefix(name, tail, font_row, content_width, d),
                font=font_row,
                fill='black',
            )
            y_pos += row_advance

            if y_pos > large_height - 30 * scale:
                break

    return img.resize((width, height), Image.LANCZOS)


def _todo_capacity(
    height: int,
    columns: int,
    title_font_size: int = COMPONENT_TITLE_FONT_SIZE,
    title_lines: int = 1,
    logger: "Logger | None" = None,
) -> tuple[int, int]:
    """Compute todo-list page capacity for a component of the given height.

    Works in unscaled pixels (the draw function applies its own scale). The
    row count is scale-invariant, so this and the draw function agree.

    Args:
        height: Component (tile) height in unscaled pixels.
        columns: Number of columns (>= 1).
        title_font_size: Unscaled title font size the panel will draw with.
        title_lines: Number of title lines the panel will draw. At 1 (the
            default) capacity matches the legacy TODO_HEADER_H exactly.
        logger: Logger instance, passed through to the band-height
            measurement when title_lines > 1.

    Returns:
        (rows_per_column, capacity) where capacity = rows_per_column * columns.
    """
    cols = columns if isinstance(columns, int) and columns > 0 else 1
    header = _todo_header_height(title_font_size, title_lines, logger)
    body = height - header - TODO_BOTTOM_PAD
    rows_per_column = max(1, body // TODO_ROW_H)
    return rows_per_column, rows_per_column * cols


def _draw_todo_list_component(
    friendly_name: str,
    items: list[dict[str, str]],
    width: int,
    height: int,
    logger: "Logger",
    *,
    columns: int = 1,
    page: int = 0,
    title_font_size: int | None = None,
    title_lines: int = 1,
    body_font_size: int | None = None,
) -> Image.Image:
    """Draws a todo list with checkboxes, columns, and pagination.

    Incomplete items are laid out column-major across `columns` columns. When
    they overflow one screenful, the list paginates: `page` selects which
    screenful to show (wrapping), and a page indicator is drawn. The title
    shows the total incomplete count.

    Args:
        friendly_name: Display name for the component
        items: List of todo items with 'summary' and 'status' keys
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        columns: Number of columns (>= 1; invalid coerced to 1)
        page: Page index to render (wrapped modulo the page count)
        body_font_size: Item size resolved by the caller so every panel in the
            layout row agrees. When None, this panel picks its own rung.
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
        title_lines: Number of title lines to wrap onto. At 1 (the default)
            content starts at the legacy fixed offset unconditionally.

    Returns:
        Rendered PIL Image
    """
    cols: int = columns if isinstance(columns, int) and columns > 0 else 1
    scale: int = COMPONENT_SCALE
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        resolved_title_size: int = (
            title_font_size if title_font_size is not None else COMPONENT_TITLE_FONT_SIZE
        ) * scale
        font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        font_indicator = ImageFont.truetype(NOTO_FONT, 18 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_indicator = ImageFont.load_default()

    incomplete: list[dict[str, str]] = _incomplete_items(items)
    total: int = len(incomplete)

    # Title with count.
    title_text: str = f"{friendly_name} ({total})"
    if title_lines > 1:
        title_lines_text: list[str] = _wrap_title(
            title_text, font_title, large_width - TITLE_PADDING * scale, title_lines
        ) or [title_text]
    else:
        title_lines_text = [title_text]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - TITLE_PADDING * scale, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    title_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                      spacing=TITLE_LINE_SPACING * scale)
    title_width: int = title_bbox[2] - title_bbox[0]
    d.multiline_text(
        ((large_width - title_width) / 2, 5 * scale), rendered_title,
        font=font_title, fill='black', align='center',
        spacing=TITLE_LINE_SPACING * scale,
    )

    header_y: int = _todo_header_height(title_font_size, title_lines, logger) * scale

    if total == 0:
        msg: str = "No items to display"
        font_item = font_indicator
        try:
            font_item = ImageFont.truetype(NOTO_FONT, 28 * scale)
        except IOError:
            pass
        msg_bbox = d.textbbox((0, 0), msg, font=font_item)
        msg_width: int = msg_bbox[2] - msg_bbox[0]
        d.text(((large_width - msg_width) / 2, header_y), msg, font=font_item, fill='black')
        return img.resize((width, height), Image.LANCZOS)

    rows_per_column, capacity = _todo_capacity(height, cols, title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger)
    num_pages: int = max(1, ceil(total / capacity))
    page_idx: int = page % num_pages
    page_items: list[dict[str, str]] = incomplete[page_idx * capacity:(page_idx + 1) * capacity]

    # Page indicator (top-right) only when paginating.
    if num_pages > 1:
        indicator: str = f"{page_idx + 1}/{num_pages}"
        ind_bbox = d.textbbox((0, 0), indicator, font=font_indicator)
        ind_width: int = ind_bbox[2] - ind_bbox[0]
        d.text((large_width - ind_width - 10 * scale, 12 * scale), indicator, font=font_indicator, fill='black')

    row_h: int = TODO_ROW_H * scale
    checkbox_size: int = 24 * scale
    col_width: int = large_width // cols

    # Every column is the same width, so one size serves the whole page and the
    # summaries no longer step between sizes down a single column. The caller
    # may supply a size agreed across the whole layout row instead.
    text_offset: int = 15 * scale + checkbox_size + 8 * scale
    available_width: int = col_width - text_offset - 8 * scale
    summaries: list[str] = [item.get('summary', '') for item in page_items]
    font_item_row = _load_font(
        (body_font_size if body_font_size is not None
         # Sized against every incomplete item, not just this page's: the
         # panel re-renders on a different page each refresh, and sizing per
         # page would make the text jump between sizes as it cycles.
         else _fit_body_size(_todo_row_texts(items), available_width, logger)) * scale,
        logger,
    )
    # Shared vertical offset within the checkbox row: centring each summary on
    # its own ink box would leave baselines stepping up and down the column.
    item_probe = d.textbbox((0, 0), "Ag", font=font_item_row)
    text_dy: int = (checkbox_size - (item_probe[3] - item_probe[1])) // 2

    for i, raw_summary in enumerate(summaries):
        col: int = i // rows_per_column
        row: int = i % rows_per_column
        col_x: int = col * col_width
        y: int = header_y + row * row_h

        checkbox_x: int = col_x + 15 * scale
        d.rectangle(
            [(checkbox_x, y), (checkbox_x + checkbox_size, y + checkbox_size)],
            outline='black',
            width=2,
        )

        text_x: int = col_x + text_offset
        # Still too wide at the ladder floor -> ellipsis-truncate.
        summary: str = _ellipsize(raw_summary, font_item_row, available_width, d)

        d.text((text_x, y + text_dy), summary, font=font_item_row, fill='black')

    return img.resize((width, height), Image.LANCZOS)


def eink_display(png_file_object: BytesIO) -> BytesIO:
    """Converts a PNG to black and white for e-ink displays.
    
    Args:
        png_file_object: BytesIO containing PNG image data
        
    Returns:
        BytesIO containing black and white PNG image
    """
    with Image.open(png_file_object) as img:
        # Convert to black and white (1-bit pixels) without dithering
        bw_img: Image.Image = img.convert('1', dither=None)

        img_io = BytesIO()
        bw_img.save(img_io, 'PNG')
        img_io.seek(0)
        return img_io


def tile_components(
    component_render_data: list[RenderData],
    width: int,
    height: int,
    top_margin: int,
    logger: "Logger",
) -> Image.Image:
    """Calculates layout, renders components, and tiles them.
    
    Args:
        component_render_data: List of component render data
        width: Total image width
        height: Total image height
        top_margin: Top margin for header
        logger: Logger instance
        
    Returns:
        Tiled PIL Image
    """
    from .state import server_state

    if not component_render_data:
        return Image.new('RGB', (width, height), color='white')

    final_image: Image.Image = Image.new('RGB', (width, height), color='white')

    large_component_data: RenderData | None = None
    other_components_data: list[RenderData] = []
    large_component_found: bool = False
    for comp_data in component_render_data:
        if comp_data.get('large_display') and not large_component_found:
            large_component_data = comp_data
            large_component_found = True
        else:
            other_components_data.append(comp_data)

    def _render_component(
        render_data: RenderData,
        tile_width: int,
        tile_height: int,
        title_font_size: int,
        title_lines: int = 1,
        body_font_size: int | None = None,
    ) -> Image.Image:
        component_type: str = render_data['type']
        friendly_name: str = render_data.get('friendly_name', '')
        data: object = render_data['data']

        if data is None:
            return _create_info_image(f"No data for\n{friendly_name}", tile_width, tile_height, logger)
        elif component_type == 'history_graph':
            window_end_val = render_data.get('window_end')
            window_start_val = render_data.get('window_start')
            if window_start_val is None or window_end_val is None:
                window_end_val = datetime.now().astimezone()
                window_start_val = window_end_val - timedelta(hours=24)
            return _draw_graph_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                window_start=window_start_val,
                window_end=window_end_val,
                zero_baseline=bool(render_data.get('zero_baseline', False)),
                title_font_size=title_font_size,
                title_lines=title_lines,
            )
        elif component_type in ('entity', 'url'):
            return _draw_entity_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                title_font_size=title_font_size,
                title_lines=title_lines,
            )
        elif component_type == 'calendar':
            return _draw_calendar_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                title_font_size=title_font_size,
                title_lines=title_lines,
                body_font_size=body_font_size,
            )
        elif component_type == 'entities':
            return _draw_entities_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                title_font_size=title_font_size,
                title_lines=title_lines,
                body_font_size=body_font_size,
            )
        elif component_type == 'todo_list':
            todo_columns = render_data.get('columns', 1)
            todo_key = render_data.get('todo_key')
            items_list = data if isinstance(data, list) else []
            total_incomplete = len(_incomplete_items(items_list))
            _, capacity = _todo_capacity(
                tile_height, todo_columns, title_font_size, title_lines, logger
            )
            num_pages = max(1, ceil(total_incomplete / capacity))
            page = server_state.next_todo_page(todo_key, num_pages) if todo_key else 0
            return _draw_todo_list_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                columns=todo_columns,
                page=page,
                title_font_size=title_font_size,
                title_lines=title_lines,
                body_font_size=body_font_size,
            )
        else:
            logger.warning("Unknown component type: %s", component_type)
            return _create_info_image(f"Unknown component:\n{component_type}", tile_width, tile_height, logger)

    available_height: int = height - top_margin

    # Geometry is resolved before rendering so that each row's panels can agree
    # on one title size. A row is exactly the set of panels drawn side by side.
    rows: list[list[tuple[RenderData, int, int, int, int]]] = []

    if large_component_data:
        # Top half for the large component; it forms its own row because it has
        # the full width to itself.
        large_height: int = available_height // 2
        rows.append([(large_component_data, 0, top_margin, width, large_height)])

        num_components: int = len(other_components_data)
        if num_components > 0:
            bottom_y_start: int = top_margin + large_height
            bottom_available_height: int = height - bottom_y_start

            cols: int = num_components
            tile_width: int = width // cols
            tile_height: int = bottom_available_height

            if tile_width > 0 and tile_height > 0:
                rows.append([
                    (render_data, i * tile_width, bottom_y_start, tile_width, tile_height)
                    for i, render_data in enumerate(other_components_data)
                ])
    else:
        # Tile all in a grid
        num_components = len(component_render_data)
        num_rows: int = int(ceil(sqrt(num_components)))
        cols = int(ceil(num_components / num_rows))

        tile_width = width // cols
        tile_height = available_height // num_rows

        if tile_width > 0 and tile_height > 0:
            for row_index in range(num_rows):
                row_placements = [
                    (
                        render_data,
                        (i % cols) * tile_width,
                        top_margin + (i // cols) * tile_height,
                        tile_width,
                        tile_height,
                    )
                    for i, render_data in enumerate(component_render_data)
                    if i // cols == row_index
                ]
                if row_placements:
                    rows.append(row_placements)

    for row in rows:
        # Panels rendering as no-data placeholders draw a centred message rather
        # than a title, so they must not drag their neighbours' size down.
        tile_height_for_row: int = row[0][4]
        row_panels = [
            (render_data, tile_w)
            for render_data, _, _, tile_w, _ in row
            if _panel_draws_a_title(render_data)
        ]

        s1: int = min(
            (
                _fit_title_size(_panel_title_text(render_data), tile_w, logger)
                for render_data, tile_w in row_panels
            ),
            default=COMPONENT_TITLE_FONT_SIZE,
        )

        cap: int = tile_height_for_row * TITLE_BAND_MAX_PERCENT // 100
        s2_results: list[int | None] = [
            _fit_title_size(
                _panel_title_text(render_data), tile_w, logger,
                lines=TITLE_MAX_LINES, max_band=cap,
            )
            for render_data, tile_w in row_panels
        ]
        # Materialise and check for None BEFORE min(): min() over a mix of
        # None and int raises TypeError.
        s2: int | None = (
            None
            if (not s2_results or any(r is None for r in s2_results))
            else min(s2_results)
        )

        if s2 is not None and (
            TITLE_SIZE_LADDER.index(s1) - TITLE_SIZE_LADDER.index(s2) >= TITLE_WRAP_MIN_GAIN
        ):
            title_font_size, title_lines = s2, TITLE_MAX_LINES
        else:
            title_font_size, title_lines = s1, 1

        # Body rows harmonise the same way titles do: the row settles on the
        # smallest size any of its list-style panels needs, so a list beside a
        # list reads as one block rather than two unrelated type sizes.
        body_fits: list[int] = [
            fit
            for fit in (
                _panel_body_fit(render_data, tile_w, logger)
                for render_data, _, _, tile_w, _ in row
            )
            if fit is not None
        ]
        body_font_size: int | None = min(body_fits) if body_fits else None

        for render_data, x, y, tile_w, tile_h in row:
            component_image = _render_component(render_data, tile_w, tile_h,
                                                title_font_size, title_lines,
                                                body_font_size)
            if component_image:
                final_image.paste(component_image, (x, y))

    return final_image


def render_dashboard_image(
    dashboard: DashboardConfig,
    logger: "Logger",
    device_id: str | None = None,
    device_rotate: int | None = None,
    *,
    now: datetime | None = None,
) -> BytesIO:
    """Renders a dashboard with multiple components into a single image.
    
    Args:
        dashboard: Dashboard configuration
        logger: Logger instance
        
    Returns:
        BytesIO containing the rendered PNG image
    """
    from datetime import datetime, timezone
    from .models import ComponentConfig
    from .hass_client import (
        get_entity_state,
        _fetch_history,
        _fetch_calendar_events,
        _process_history_to_points,
        _cast_to_numbers,
        _select_entity_value,
    )
    from .state import server_state
    
    WIDTH: int = 800
    HEIGHT: int = 480
    TOP_MARGIN: int = 40

    components: list[ComponentConfig] = dashboard.get('components', [])
    title: str = dashboard.get('title', '')

    render_now: datetime = now if now is not None else datetime.now().astimezone()
    component_render_data: list[RenderData] = []
    for component_index, component in enumerate(components):
        component_type: str | None = component.get('type')
        data: object = None
        graph_window: tuple[datetime, datetime] | None = None
        todo_meta: tuple[int, str] | None = None
        graph_zero_baseline: bool = False

        if component_type == 'history_graph':
            entity_name = component.get('entity_name', '')
            hours = component.get('hours', 24)
            if isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
                logger.warning(
                    "Invalid 'hours' (%r) for %s; defaulting to 24.",
                    hours, component.get('friendly_name'),
                )
                hours = 24
            window_start: datetime = render_now - timedelta(hours=hours)
            window_end: datetime = render_now
            graph_window = (window_start, window_end)
            history = _fetch_history(entity_name, logger, start=window_start, end=window_end)
            data = _process_history_to_points(history)
            graph_zero_baseline = bool(component.get('zero_baseline', False))
        elif component_type == 'entity':
            entity_name = component.get('entity_name', '')
            attribute = component.get('attribute')
            state_data = get_entity_state(entity_name, logger)
            data = _select_entity_value(state_data, attribute, entity_name, logger)
            if data:
                data = _cast_to_numbers(data)
        elif component_type == 'calendar':
            args = component.get('arguments', {})
            calendar_id: str | None = args.get('calendar_id')
            if calendar_id:
                days: int = args.get('days', 1)
                data = _fetch_calendar_events(calendar_id, days=days, logger=logger)
            else:
                logger.warning(
                    "Calendar component for entity %s is missing 'calendar_id' in arguments.",
                    component.get('friendly_name'),
                )
        elif component_type == 'entities':
            entity_list = component.get('entities', [])
            entity_states: list[dict[str, str | float | None]] = []
            for item in entity_list:
                entity_name = item.get('entity_name', '')
                attribute = item.get('attribute')
                state_data = get_entity_state(entity_name, logger)
                state: str | float | None = _select_entity_value(
                    state_data, attribute, entity_name, logger,
                )
                if state:
                    state = _cast_to_numbers(state)
                entity_states.append({
                    'friendly_name': item.get('friendly_name', ''),
                    'state': state,
                })
            data = entity_states
        elif component_type == 'url':
            from .url_source import fetch_url_value
            data = fetch_url_value(component, logger)
        elif component_type == 'todo_list':
            from .hass_client import _fetch_todo_list
            entity_name = component.get('entity_name', '')
            data = _fetch_todo_list(entity_name, logger)
            todo_columns = component.get('columns', 1)
            if isinstance(todo_columns, bool) or not isinstance(todo_columns, int) or todo_columns <= 0:
                logger.warning(
                    "Invalid 'columns' (%r) for %s; defaulting to 1.",
                    todo_columns, component.get('friendly_name'),
                )
                todo_columns = 1
            dashboard_name: str = dashboard.get('name', '')
            todo_key: str = f"{device_id}:{dashboard_name}:{entity_name}:{component_index}"
            todo_meta = (todo_columns, todo_key)
        else:
            logger.warning("Unknown component type %r — component will be skipped.", component_type)

        render_entry: RenderData = {
            'type': component_type or 'unknown',
            'friendly_name': component.get('friendly_name', ''),
            'data': data,
            'large_display': component.get('large_display', False),
        }
        if graph_window is not None:
            render_entry['window_start'] = graph_window[0]
            render_entry['window_end'] = graph_window[1]
        if graph_zero_baseline:
            render_entry['zero_baseline'] = True
        if todo_meta is not None:
            render_entry['columns'] = todo_meta[0]
            render_entry['todo_key'] = todo_meta[1]
        component_render_data.append(render_entry)

    if not component_render_data:
        final_img: Image.Image = _create_info_image("Dashboard has no components", WIDTH, HEIGHT, logger)
    else:
        final_img = tile_components(component_render_data, WIDTH, HEIGHT, TOP_MARGIN, logger)

        # Draw current time and title
        draw = ImageDraw.Draw(final_img)
        font_value = _load_font(30, logger)

        current_time_text: str = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        draw.text((5, 0), current_time_text, font=font_value, fill='black')

        if title:
            text_bbox = draw.textbbox((0, 0), title, font=font_value)
            text_width: int = text_bbox[2] - text_bbox[0]
            draw.text(((WIDTH - text_width) / 2, 0), title, font=font_value, fill='black')

        # Render battery percentage
        battery_voltage: float | None = server_state.consume_battery_voltage(device_id) if device_id else None
        if battery_voltage is not None:
            try:
                from .metrics import voltage_to_percent
                pct: int = voltage_to_percent(battery_voltage)
                battery_text: str = f"{pct}%"

                text_bbox = draw.textbbox((0, 0), battery_text, font=font_value)
                text_width = text_bbox[2] - text_bbox[0]
                x: int = WIDTH - text_width - 5
                y: int = 0
                draw.text((x, y), battery_text, font=font_value, fill='black')
            except (ValueError, TypeError):
                logger.warning("Invalid battery voltage value: %s", battery_voltage)

        draw.line([(0, TOP_MARGIN - 1), (WIDTH, TOP_MARGIN - 1)], fill='black', width=1)

    # Rotate image if requested (device-level overrides dashboard-level)
    rotate = device_rotate if device_rotate is not None else _dashboard_rotation(dashboard)
    final_img = _rotate_image(final_img, rotate, logger)

    # Save to memory
    img_io = BytesIO()
    final_img.save(img_io, 'PNG')
    img_io.seek(0)
    return eink_display(img_io)
