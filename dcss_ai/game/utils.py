"""Utility functions and constants for DCSS game module."""
import re


def _strip_formatting(text: str) -> str:
    """Strip DCSS formatting codes from text (e.g. color tags)."""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'§.', '', text)
    return text.strip()


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)


class Direction:
    N = "n"; S = "s"; E = "e"; W = "w"
    NE = "ne"; NW = "nw"; SE = "se"; SW = "sw"
