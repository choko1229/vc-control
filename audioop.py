"""
Compatibility shim for the removed :mod:`audioop` module on Python 3.13+.

Py-cord's voice player imports :mod:`audioop` for the ``mul`` helper used in
volume adjustments. Python 3.13 removed the stdlib module, which causes the bot
process to crash during startup in environments such as Pterodactyl. This file
provides a tiny, pure-Python replacement that supports the subset of
functionality the bot (and py-cord) rely on.

The implementation intentionally mirrors the legacy interface closely so that
existing code continues to behave as expected.
"""
from __future__ import annotations

from array import array
from typing import Iterable


class error(Exception):
    """Mimic the built-in ``audioop.error`` exception type."""


def _get_typecode(width: int) -> str:
    if width == 1:
        return "b"
    if width == 2:
        return "h"
    if width == 4:
        return "i"
    raise error(f"unsupported sample width: {width}")


def _clip(value: int, width: int) -> int:
    max_value = (1 << (8 * width - 1)) - 1
    min_value = -1 << (8 * width - 1)
    return max(min_value, min(max_value, value))


def _scale_samples(samples: Iterable[int], width: int, factor: float) -> array:
    scaled = array(_get_typecode(width))
    for sample in samples:
        scaled.append(_clip(int(sample * factor), width))
    return scaled


def mul(fragment: bytes | bytearray, width: int, factor: float) -> bytes:
    """Multiply audio samples by ``factor``.

    This mirrors ``audioop.mul`` sufficiently for py-cord's usage:

    - Supports widths of 1, 2, or 4 bytes.
    - Accepts ``bytes`` or ``bytearray`` buffers.
    - Clamps samples to the valid range for the given width.

    Parameters
    ----------
    fragment: bytes or bytearray
        Raw PCM audio data.
    width: int
        Sample width in bytes (1, 2, or 4).
    factor: float
        Multiplier applied to each sample.
    """

    if not isinstance(fragment, (bytes, bytearray)):
        raise error("fragment must be bytes-like")

    samples = array(_get_typecode(width))
    samples.frombytes(fragment)
    scaled = _scale_samples(samples, width, factor)
    return scaled.tobytes()

