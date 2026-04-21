"""Server-sent event formatting helper."""

from __future__ import annotations


def format_sse(event: str, data: str) -> str:
    """Format a single server-sent event frame.

    Produces the wire format consumed by the browser EventSource API::

        event: <event>
        data: <data>

    """
    return f"event: {event}\ndata: {data}\n\n"
