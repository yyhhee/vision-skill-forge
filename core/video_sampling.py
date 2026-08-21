from __future__ import annotations


def normalize_end_seconds(value: float | int | str | None) -> float | None:
    """Normalize the optional video segment end used by every sampling path."""

    if value in (None, ""):
        return None
    end_seconds = float(value)
    # Gradio can serialize an empty Number as 0.0. A zero-length selection is
    # not executable, so preserve the UI's documented "to the end" meaning.
    return None if end_seconds == 0.0 else end_seconds

