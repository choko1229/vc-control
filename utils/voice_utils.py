"""Helper utilities for voice state change detection."""

import discord


def is_channel_transition(before: discord.VoiceState, after: discord.VoiceState) -> bool:
    """Return True if the member moved between voice channels.

    This ignores updates within the same channel (mute/deafen/screen-share),
    and only reports transitions where the channel reference actually changes.
    """

    return before.channel != after.channel


def active_seconds(participant: dict, now: discord.utils.utcnow = discord.utils.utcnow) -> int:
    """Calculate current participation seconds for a tracked participant.

    The participant dict is expected to contain ``total_sec`` and an optional
    ``joined_at`` datetime; the live duration is added when ``joined_at`` is
    present.
    """

    total = int(participant.get("total_sec", 0))
    joined_at = participant.get("joined_at")
    if joined_at:
        total += int((now() - joined_at).total_seconds())
    return total
