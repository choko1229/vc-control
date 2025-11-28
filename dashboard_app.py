# dashboard_app.py

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import json
import settings
from utils import db_utils  # 履歴用（既に作っているはず）


templates = Jinja2Templates(directory="templates")


class DashboardState:
    """
    WebSocket 接続の管理＋VC状況のブロードキャスト担当
    bot.dashboard に入るオブジェクト
    """
    def __init__(self):
        self.websockets: set[WebSocket] = set()

    async def register(self, ws: WebSocket):
        self.websockets.add(ws)

    def unregister(self, ws: WebSocket):
        if ws in self.websockets:
            self.websockets.remove(ws)

    async def broadcast_vc_update(self, bot):
        """
        現在の VC 状況を全 WebSocket クライアントへブロードキャスト
        """
        if not self.websockets:
            return

        payload = []

        for g in bot.guilds:
            guild_info = {
                "id": g.id,
                "name": g.name,
                "vcs": []
            }
            for ch in g.voice_channels:
                if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                    guild_info["vcs"].append(
                        {
                            "id": ch.id,
                            "name": ch.name,
                            "members": [m.display_name for m in ch.members],
                        }
                    )
            payload.append(guild_info)

        message = json.dumps({"type": "vc_update", "guilds": payload}, ensure_ascii=False)

        dead = []
        for ws in list(self.websockets):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.unregister(ws)


def create_app(bot, dashboard_state: DashboardState) -> FastAPI:
    app = FastAPI(title="VC Dashboard")

    # ─────────────────────
    # トップページ：ギルド一覧
    # ─────────────────────
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

    # ─────────────────────
    # ギルド詳細ページ：現在VC＋履歴表示
    # ─────────────────────
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

        # SQLite から直近50件の履歴取得
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

    # ─────────────────────
    # WebSocket: VC状況リアルタイム更新
    # ─────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        await dashboard_state.register(ws)
        try:
            # クライアントからのメッセージは特に使わず、接続維持だけ
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            dashboard_state.unregister(ws)
        except Exception:
            dashboard_state.unregister(ws)

    # ─────────────────────
    # API: 状態確認用
    # ─────────────────────
    @app.get("/api/status")
    async def api_status():
        return {
            "guilds": len(bot.guilds),
            "user": str(bot.user) if bot.user else None,
        }

    return app
