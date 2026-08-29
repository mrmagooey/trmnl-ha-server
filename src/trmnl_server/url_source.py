"""Non-Home-Assistant data sources for trmnl-server.

Fetches text from an arbitrary HTTP(S) URL and extracts a value from it,
either with a jq-style JSON path or a regex. Fetches happen on a background
thread pool and are cached, so the render path never waits on the network.
"""

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


def _json_path(obj: object, path: str) -> object | None:
    """Resolve a basic jq-style path against a decoded JSON object.

    Supports dot-separated keys and bracketed integer indices, e.g.
    ``.data.items[0].name``. The leading dot is optional.

    Args:
        obj: Decoded JSON value to traverse.
        path: The path expression.

    Returns:
        The value at the path, or None if any step is missing, out of range,
        traverses into a non-container, or is malformed.
    """
    current: object = obj
    for token in _tokenise_path(path):
        match = _INDEX_RE.match(token)
        if match is not None:
            if not isinstance(current, list):
                return None
            index = int(match.group(1))
            if not -len(current) <= index < len(current):
                return None
            current = current[index]
        elif token.startswith("["):
            return None  # malformed index, e.g. [x]
        else:
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
    return current


def _tokenise_path(path: str) -> list[str]:
    """Split a path into key and ``[index]`` tokens.

    Args:
        path: The path expression, with or without a leading dot.

    Returns:
        Token list; empty for an empty path (the identity path).
    """
    tokens: list[str] = []
    for part in path.lstrip(".").split("."):
        if not part:
            continue
        head, _, rest = part.partition("[")
        if head:
            tokens.append(head)
        if rest:
            tokens.extend(f"[{chunk}" for chunk in rest.split("[") if chunk)
    return tokens


def _stringify(value: object) -> str | None:
    """Render an extracted JSON value as display text.

    Strings pass through unquoted; everything else is JSON-encoded, so
    containers become JSON text rather than a Python repr and booleans render
    as ``true``/``false``.

    Args:
        value: The extracted value.

    Returns:
        The text, or None for JSON null.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def extract_value(
    body: str,
    *,
    json_path: str | None,
    regex: str | None,
    logger: "Logger",
) -> str | None:
    """Extract display text from a response body.

    Applies ``json_path`` first (if set), then ``regex`` (if set) to the
    result. With neither set the stripped body is returned.

    Args:
        body: The raw response body.
        json_path: Optional jq-style path.
        regex: Optional pattern; group 1 if the pattern has groups, else group 0.
        logger: Logger for extraction warnings.

    Returns:
        The extracted text, or None if any step fails to produce a value.
    """
    if not body:
        return None

    value: object = body
    if json_path:
        try:
            decoded = json.loads(body)
        except ValueError:
            logger.warning("Response is not valid JSON; cannot apply json_path %r.", json_path)
            return None
        value = _json_path(decoded, json_path)
        if value is None:
            logger.warning("json_path %r matched nothing in the response.", json_path)
            return None

    text: str | None = _stringify(value)
    if text is None:
        return None

    if regex:
        try:
            match = re.search(regex, text)
        except re.error as e:
            logger.warning("Invalid regex %r: %s", regex, e)
            return None
        if match is None:
            logger.warning("regex %r matched nothing in the response.", regex)
            return None
        text = match.group(1) if match.re.groups else match.group(0)

    text = text.strip()
    return text or None
