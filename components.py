"""Component rendering functions for e-ink displays.

This module contains all the rendering functions for different component types
(history graphs, entities, calendars, etc.).
"""

from datetime import datetime, timedelta
from io import BytesIO
from math import ceil, sqrt
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from models import CalendarEvent, DashboardConfig, RenderData

if TYPE_CHECKING:
    from logging import Logger

# Constants
COMPONENT_TITLE_FONT_SIZE: int = 35
NOTO_FONT: str = "NotoSans-Regular.ttf"
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


def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float]],
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Draws a single history graph component.
    
    Args:
        friendly_name: Display name for the component
        data_points: List of (timestamp, value) tuples
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    # Create a larger image for antialiasing
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    # Load fonts
    try:
        title_font_size: int = COMPONENT_TITLE_FONT_SIZE * scale
        padding: int = 20 * scale
        font_title = ImageFont.truetype(NOTO_FONT, title_font_size)
        title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
        title_width_val: int = title_bbox[2] - title_bbox[0]
        
        while title_width_val > large_width - padding:
            title_font_size -= 2
            if title_font_size <= 8:
                break
            font_title = ImageFont.truetype(NOTO_FONT, title_font_size)
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
    margin: int = 40 * scale
    margin_right: int = ceil(margin * 1.6)
    graph_width: int = large_width - margin - margin_right
    graph_height: int = large_height - 2 * margin - (10 * scale)

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
    text_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
    text_width = text_bbox[2] - text_bbox[0]
    d.text(((large_width - text_width) / 2, 2 * scale), friendly_name, font=font_title, fill='black')

    # Process data
    times: tuple[datetime, ...]
    values: tuple[float, ...]
    times, values = zip(*data_points)
    min_time: datetime = min(times)
    max_time: datetime = max(times)
    min_val: float = min(values)
    max_val: float = max(values)

    # Avoid division by zero
    if max_val == min_val:
        max_val += 1
        min_val -= 1

    time_delta: timedelta = max_time - min_time
    if time_delta.total_seconds() == 0:
        time_delta = timedelta(seconds=1)

    # Draw axes
    d.line(
        [(margin, margin), (margin, large_height - margin)],
        fill='black',
        width=scale * 2,
    )
    d.line(
        [(margin, large_height - margin), (large_width - margin_right, large_height - margin)],
        fill='black',
        width=scale * 2,
    )

    # Draw Y-axis labels
    num_y_labels: int = 3
    for i in range(num_y_labels + 1):
        val: float = min_val + (max_val - min_val) * i / num_y_labels
        y: float = (large_height - margin) - (i / num_y_labels) * graph_height
        if i == 0:
            y -= 10
        label: str = f"{val:.1f}"
        text_bbox = d.textbbox((0, 0), label, font=font_axes)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        d.text(
            (margin - text_width - (5 * scale), y - text_height / 2),
            label,
            font=font_axes,
            fill='black',
        )
        d.line([(margin - (5 * scale), y), (margin, y)], fill='black', width=scale)

    # Draw X-axis labels
    if (max_time - min_time).total_seconds() > 0:
        num_x_labels: int = 4
        for i in range(num_x_labels + 1):
            time_point: datetime = min_time + (max_time - min_time) * i / num_x_labels
            x: float = margin + (i / num_x_labels) * graph_width
            label = time_point.astimezone().strftime("%H:%M")
            text_bbox = d.textbbox((0, 0), label, font=font_axes)
            text_width = text_bbox[2] - text_bbox[0]
            d.text(
                (x - text_width / 3, large_height - margin + (5 * scale)),
                label,
                font=font_axes,
                fill='black',
            )
            d.line(
                [(x, large_height - margin), (x, large_height - margin + (5 * scale))],
                fill='black',
                width=scale,
            )

    # Helper to convert data to pixel coordinates
    def to_coords(t: datetime, v: float) -> tuple[float, float]:
        x: float = margin + ((t - min_time) / time_delta) * graph_width
        y: float = (large_height - margin) - ((v - min_val) / (max_val - min_val)) * graph_height
        return x, y

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

    return img.resize((width, height), Image.LANCZOS)


def _draw_entity_component(
    friendly_name: str,
    value: str | float | int | None,
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Draws a single entity component.
    
    Args:
        friendly_name: Display name for the component
        value: Entity state value
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    # Dynamically adjust title font size
    title_font_size: int = COMPONENT_TITLE_FONT_SIZE * scale
    padding: int = 20 * scale
    font_title = ImageFont.load_default()
    try:
        font_title = ImageFont.truetype(NOTO_FONT, title_font_size)
        title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
        title_width_val: int = title_bbox[2] - title_bbox[0]

        while title_width_val > large_width - padding:
            title_font_size -= 2
            if title_font_size <= 8:
                break
            font_title = ImageFont.truetype(NOTO_FONT, title_font_size)
            title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
            title_width_val = title_bbox[2] - title_bbox[0]
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True

    y_tweak: int = 40
    # Draw title
    title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
    title_width: int = title_bbox[2] - title_bbox[0]
    title_x: float = (large_width - title_width) / 2
    title_y: float = 20 * scale - y_tweak
    d.text((title_x, title_y), friendly_name, font=font_title, fill='black')

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

        while value_width > large_width - padding:
            font_size -= 4
            if font_size <= min_font_size:
                break
            font_value = ImageFont.truetype(NOTO_FONT, font_size)
            value_bbox = d.textbbox((0, 0), value_str, font=font_value)
            value_width = value_bbox[2] - value_bbox[0]

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
    except IOError:
        pass  # Use default font

    # Center value
    value_bbox = d.textbbox((0, 0), value_str, font=font_value)
    value_width = value_bbox[2] - value_bbox[0]
    value_height: int = value_bbox[3] - value_bbox[1]

    value_x: float = (large_width - value_width) / 2
    final_y_tweak: int = y_tweak if '\n' not in value_str else 0
    value_y: float = (large_height - value_height) / 2 - final_y_tweak

    d.text((value_x, value_y), value_str, font=font_value, fill='black', align='center')

    return img.resize((width, height), Image.LANCZOS)


def _draw_calendar_component(
    friendly_name: str,
    events: list[CalendarEvent],
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Draws a calendar component.
    
    Args:
        friendly_name: Display name for the component
        events: List of calendar events
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    from datetime import date as dt_date
    
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(NOTO_FONT, COMPONENT_TITLE_FONT_SIZE * scale)
        font_event = ImageFont.truetype(NOTO_FONT, 28 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_event = ImageFont.load_default()

    # Draw title
    text_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
    text_width: int = text_bbox[2] - text_bbox[0]
    d.text(((large_width - text_width) / 2, 5 * scale), friendly_name, font=font_title, fill='black')

    y_pos: int = 50 * scale
    line_spacing: int = 8 * scale

    if not events:
        msg: str = "No upcoming events"
        text_bbox = d.textbbox((0, 0), msg, font=font_event)
        text_width = text_bbox[2] - text_bbox[0]
        d.text(((large_width - text_width) / 2, y_pos), msg, font=font_event, fill='black')
    else:
        # Sort events
        def get_sort_key(event: CalendarEvent) -> str:
            start = event.get('start', {})
            return start.get('dateTime') or start.get('date') or 'z'
        events.sort(key=get_sort_key)

        for event in events:
            from pprint import pformat as pf
            logger.debug("calendar event: %s", pf(event))
            summary: str = event.get('summary', 'No summary')
            start = event.get('start', {})
            end = event.get('end', {})

            # Format event string
            start_date_time = start.get('dateTime')
            start_date = start.get('date')
            end_date_time = end.get('dateTime')
            if start_date_time:  # Timed event
                start_dt: datetime = datetime.fromisoformat(start_date_time).astimezone()
                end_dt: datetime = datetime.fromisoformat(end_date_time).astimezone() if end_date_time else start_dt
                day_name: str = start_dt.strftime('%A')
                event_str: str = f"{day_name} {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}: {summary}"
            elif start_date:  # All-day event
                start_date_obj = dt_date.fromisoformat(start_date)
                day_name = start_date_obj.strftime('%A')
                event_str = f"{day_name} All day: {summary}"
            else:
                event_str = f"Unknown: {summary}"

            # Adjust font size
            font_size: int = 28 * scale
            padding: int = 40 * scale
            try:
                dynamic_font_event = ImageFont.truetype(NOTO_FONT, font_size)
                event_bbox = d.textbbox((0, 0), event_str, font=dynamic_font_event)
                event_width: int = event_bbox[2] - event_bbox[0]

                while event_width > large_width - padding:
                    font_size -= 2
                    if font_size <= 8:
                        break
                    dynamic_font_event = ImageFont.truetype(NOTO_FONT, font_size)
                    event_bbox = d.textbbox((0, 0), event_str, font=dynamic_font_event)
                    event_width = event_bbox[2] - event_bbox[0]
            except IOError:
                dynamic_font_event = ImageFont.load_default()

            d.text((20 * scale, y_pos), event_str, font=dynamic_font_event, fill='black')
            event_bbox = d.textbbox((0, 0), event_str, font=dynamic_font_event)
            event_height: int = event_bbox[3] - event_bbox[1]
            y_pos += event_height + line_spacing

            if y_pos > large_height - 30 * scale:
                break

    return img.resize((width, height), Image.LANCZOS)


def _draw_entities_component(
    friendly_name: str,
    entity_states: list[dict[str, str | float | None]],
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Draws a list of entities and their states.
    
    Args:
        friendly_name: Display name for the component
        entity_states: List of entity state dictionaries
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(NOTO_FONT, COMPONENT_TITLE_FONT_SIZE * scale)
        font_list = ImageFont.truetype(NOTO_FONT, 28 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_list = ImageFont.load_default()

    # Draw title
    text_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
    text_width: int = text_bbox[2] - text_bbox[0]
    d.text(((large_width - text_width) / 2, 5 * scale), friendly_name, font=font_title, fill='black')

    y_pos: int = 50 * scale
    line_spacing: int = 8 * scale

    if not entity_states:
        msg: str = "No entities to display"
        text_bbox = d.textbbox((0, 0), msg, font=font_list)
        text_width = text_bbox[2] - text_bbox[0]
        d.text(((large_width - text_width) / 2, y_pos), msg, font=font_list, fill='black')
    else:
        for entity in entity_states:
            name = str(entity.get('friendly_name', ''))  # type: ignore[arg-type]
            state: str | float | None = entity.get('state', 'N/A')

            if isinstance(state, float):
                state_str: str = f"{state:.2f}"
            else:
                state_str = str(state)

            list_str: str = f"{name}: {state_str}"

            # Adjust font size
            font_size: int = 28 * scale
            padding: int = 40 * scale
            try:
                dynamic_font_list = ImageFont.truetype(NOTO_FONT, font_size)
                list_bbox = d.textbbox((0, 0), list_str, font=dynamic_font_list)
                list_width: int = list_bbox[2] - list_bbox[0]

                while list_width > large_width - padding:
                    font_size -= 2
                    if font_size <= 8:
                        break
                    dynamic_font_list = ImageFont.truetype(NOTO_FONT, font_size)
                    list_bbox = d.textbbox((0, 0), list_str, font=dynamic_font_list)
                    list_width = list_bbox[2] - list_bbox[0]
            except IOError:
                dynamic_font_list = ImageFont.load_default()

            d.text((20 * scale, y_pos), list_str, font=dynamic_font_list, fill='black')
            list_bbox = d.textbbox((0, 0), list_str, font=dynamic_font_list)
            list_height: int = list_bbox[3] - list_bbox[1]
            y_pos += list_height + line_spacing

            if y_pos > large_height - 30 * scale:
                break

    return img.resize((width, height), Image.LANCZOS)


def _draw_todo_list_component(
    friendly_name: str,
    items: list[dict[str, str]],
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
    """Draws a todo list component with checkboxes.
    
    Args:
        friendly_name: Display name for the component
        items: List of todo items with 'summary' and 'status' keys
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        
    Returns:
        Rendered PIL Image
    """
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(NOTO_FONT, COMPONENT_TITLE_FONT_SIZE * scale)
        font_item = ImageFont.truetype(NOTO_FONT, 28 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_item = ImageFont.load_default()

    # Draw title
    text_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
    text_width: int = text_bbox[2] - text_bbox[0]
    d.text(((large_width - text_width) / 2, 5 * scale), friendly_name, font=font_title, fill='black')

    y_pos: int = 50 * scale
    line_spacing: int = 12 * scale
    checkbox_size: int = 24 * scale
    text_offset: int = 10 * scale

    if not items:
        msg: str = "No items to display"
        text_bbox = d.textbbox((0, 0), msg, font=font_item)
        text_width = text_bbox[2] - text_bbox[0]
        d.text(((large_width - text_width) / 2, y_pos), msg, font=font_item, fill='black')
    else:
        for item in items:
            summary: str = item.get('summary', '')
            status: str = item.get('status', 'needs_action')
            
            # Skip completed items by default
            if status == 'completed':
                continue
            
            # Draw checkbox
            checkbox_x: int = 20 * scale
            checkbox_y: int = y_pos
            # Draw empty checkbox
            d.rectangle(
                [(checkbox_x, checkbox_y), (checkbox_x + checkbox_size, checkbox_y + checkbox_size)],
                outline='black',
                width=2,
            )
            
            # Adjust font size to fit remaining width
            font_size: int = 28 * scale
            padding: int = 60 * scale  # Space for checkbox + margins
            available_width: int = large_width - padding
            
            dynamic_font_item = ImageFont.load_default()
            item_bbox = (0, 0, 0, 0)
            
            try:
                dynamic_font_item = ImageFont.truetype(NOTO_FONT, font_size)
                item_bbox = d.textbbox((0, 0), summary, font=dynamic_font_item)
                item_width: int = item_bbox[2] - item_bbox[0]
                
                while item_width > available_width and font_size > 16:
                    font_size -= 2
                    dynamic_font_item = ImageFont.truetype(NOTO_FONT, font_size)
                    item_bbox = d.textbbox((0, 0), summary, font=dynamic_font_item)
                    item_width = item_bbox[2] - item_bbox[0]
            except IOError:
                dynamic_font_item = ImageFont.load_default()
                item_bbox = d.textbbox((0, 0), summary, font=dynamic_font_item)
            
            # Draw item text
            text_x: int = checkbox_x + checkbox_size + text_offset
            text_y: int = checkbox_y + (checkbox_size - item_bbox[3] + item_bbox[1]) // 2
            d.text((text_x, text_y), summary, font=dynamic_font_item, fill='black')
            
            y_pos += max(checkbox_size + line_spacing, item_bbox[3] - item_bbox[1] + line_spacing)
            
            if y_pos > large_height - 30 * scale:
                break

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
    ) -> Image.Image:
        component_type: str = render_data['type']
        friendly_name: str = render_data.get('friendly_name', '')
        data: object = render_data['data']

        if data is None:
            return _create_info_image(f"No data for\n{friendly_name}", tile_width, tile_height, logger)
        elif component_type == 'history_graph':
            return _draw_graph_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
        elif component_type == 'entity':
            return _draw_entity_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
        elif component_type == 'calendar':
            return _draw_calendar_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
        elif component_type == 'entities':
            return _draw_entities_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
        elif component_type == 'todo_list':
            return _draw_todo_list_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
        else:
            logger.warning("Unknown component type: %s", component_type)
            return _create_info_image(f"Unknown component:\n{component_type}", tile_width, tile_height, logger)

    available_height: int = height - top_margin

    if large_component_data:
        # Top half for large component
        large_height: int = available_height // 2
        component_image: Image.Image = _render_component(
            large_component_data,
            width,
            large_height,
        )
        if component_image:
            final_image.paste(component_image, (0, top_margin))

        # Bottom half for other components
        num_components: int = len(other_components_data)
        if num_components > 0:
            bottom_y_start: int = top_margin + large_height
            bottom_available_height: int = height - bottom_y_start

            cols: int = num_components
            tile_width: int = width // cols
            tile_height: int = bottom_available_height

            if tile_width > 0 and tile_height > 0:
                for i, render_data in enumerate(other_components_data):
                    x: int = i * tile_width
                    y: int = bottom_y_start
                    component_image = _render_component(render_data, tile_width, tile_height)
                    if component_image:
                        final_image.paste(component_image, (x, y))
    else:
        # Tile all in a grid
        num_components = len(component_render_data)
        rows: int = int(ceil(sqrt(num_components)))
        cols = int(ceil(num_components / rows))

        tile_width = width // cols
        tile_height = available_height // rows

        if tile_width > 0 and tile_height > 0:
            for i, render_data in enumerate(component_render_data):
                row: int = i // cols
                col: int = i % cols
                x = col * tile_width
                y = top_margin + row * tile_height
                component_image = _render_component(render_data, tile_width, tile_height)
                if component_image:
                    final_image.paste(component_image, (x, y))

    return final_image


def render_dashboard_image(
    dashboard: DashboardConfig,
    logger: "Logger",
    device_id: str | None = None,
) -> BytesIO:
    """Renders a dashboard with multiple components into a single image.
    
    Args:
        dashboard: Dashboard configuration
        logger: Logger instance
        
    Returns:
        BytesIO containing the rendered PNG image
    """
    from datetime import datetime, timezone
    from models import ComponentConfig
    from hass_client import (
        get_entity_state,
        _fetch_history,
        _fetch_calendar_events,
        _process_history_to_points,
        _cast_to_numbers,
    )
    from state import server_state
    
    WIDTH: int = 800
    HEIGHT: int = 480
    TOP_MARGIN: int = 40

    components: list[ComponentConfig] = dashboard.get('components', [])
    title: str = dashboard.get('title', '')

    component_render_data: list[RenderData] = []
    for component in components:
        component_type: str | None = component.get('type')
        data: object = None
        
        if component_type == 'history_graph':
            entity_name = component.get('entity_name', '')
            history = _fetch_history(entity_name, logger)
            data = _process_history_to_points(history)
        elif component_type == 'entity':
            entity_name = component.get('entity_name', '')
            state_data = get_entity_state(entity_name, logger)
            data = state_data.get('state') if state_data else None
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
                state_data = get_entity_state(entity_name, logger)
                state: str | float | None = state_data.get('state') if state_data else None
                if state:
                    state = _cast_to_numbers(state)
                entity_states.append({
                    'friendly_name': item.get('friendly_name', ''),
                    'state': state,
                })
            data = entity_states
        elif component_type == 'todo_list':
            from hass_client import _fetch_todo_list
            entity_name = component.get('entity_name', '')
            data = _fetch_todo_list(entity_name, logger)
        else:
            logger.warning("Unknown component type %r — component will be skipped.", component_type)

        component_render_data.append({
            'type': component_type or 'unknown',
            'friendly_name': component.get('friendly_name', ''),
            'data': data,
            'large_display': component.get('large_display', False),
        })

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
                # Map 2.4V..4.2V to 0..100%
                pct: int = int(round(((battery_voltage - 2.4) / (4.2 - 2.4)) * 100))
                pct = max(0, min(100, pct))
                battery_text: str = f"{pct}%"

                text_bbox = draw.textbbox((0, 0), battery_text, font=font_value)
                text_width = text_bbox[2] - text_bbox[0]
                x: int = WIDTH - text_width - 5
                y: int = 0
                draw.text((x, y), battery_text, font=font_value, fill='black')
            except (ValueError, TypeError):
                logger.warning("Invalid battery voltage value: %s", battery_voltage)

        draw.line([(0, TOP_MARGIN - 1), (WIDTH, TOP_MARGIN - 1)], fill='black', width=1)

    # Rotate image if requested
    rotate = dashboard.get('rotate')
    if rotate is None and dashboard.get('portrait'):
        rotate = 90
    if rotate in (90, -90):
        final_img = final_img.rotate(rotate, expand=True)
    elif rotate is not None:
        logger.warning("Unsupported rotate value %r — must be 90 or -90. Skipping rotation.", rotate)

    # Save to memory
    img_io = BytesIO()
    final_img.save(img_io, 'PNG')
    img_io.seek(0)
    return eink_display(img_io)
