# dashboard_app.py

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import settings
from utils import db_utils

templates = Jinja2Templates(directory="templates")


def create_app(bot) -> FastAPI:
    app = FastAPI(title="VC Dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        guild_summaries = []
        for g in bot.guilds:
            vc_count = 0
            for ch in g.voice_channels:
                if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                    vc_count += len(ch.members)

            guild_summaries.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "vc_count": vc_count,
                }
            )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "guilds": guild_summaries,
            },
        )

    @app.get("/guild/{guild_id}", response_class=HTMLResponse)
    async def guild_detail(request: Request, guild_id: int):
        guild = bot.get_guild(guild_id)
        if guild is None:
            return RedirectResponse("/")

        vc_list = []
        for ch in guild.voice_channels:
            if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                vc_list.append(
                    {
                        "id": ch.id,
                        "name": ch.name,
                        "members": [m.display_name for m in ch.members],
                    }
                )

        # ★ ここでDBから履歴を取得
        sessions = db_utils.get_sessions_by_guild(guild.id, limit=50)

        return templates.TemplateResponse(
            "guild.html",
            {
                "request": request,
                "guild": guild,
                "vc_list": vc_list,
                "sessions": sessions,
            },
        )

    @app.get("/api/status")
    async def api_status():
        return {
            "guilds": len(bot.guilds),
            "user": str(bot.user) if bot.user else None,
        }

    return app
