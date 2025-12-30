"""Helper utilities for voice state change detection."""

import discord


def is_channel_transition(before: discord.VoiceState, after: discord.VoiceState) -> bool:
    """Return True if the member moved between voice channels.

    This ignores updates within the same channel (mute/deafen/screen-share),
    and only reports transitions where the channel reference actually changes.
    """

    return before.channel != after.channel
