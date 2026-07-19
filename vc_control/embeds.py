from __future__ import annotations

from typing import Any

import discord

from vc_control.i18n import t

BRAND_BLUE = discord.Color(0x3B82F6)
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_WARNING = discord.Color.orange()
COLOR_NOTIFY = discord.Color.gold()


def build_embed(
    locale: str | None,
    title_key: str,
    description_key: str | None = None,
    *,
    color: discord.Color,
    title_fmt: dict[str, Any] | None = None,
    description_fmt: dict[str, Any] | None = None,
) -> discord.Embed:
    title = t(title_key, locale, **(title_fmt or {}))
    description = t(description_key, locale, **(description_fmt or {})) if description_key else None
    return discord.Embed(title=title, description=description, color=color)
