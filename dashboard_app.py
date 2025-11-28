# dashboard_app.py

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import aiohttp
from urllib.parse import urlencode
from typing import List, Set

import settings
from utils import db_utils  # VC履歴表示用


templates = Jinja2Templates(directory="templates")


# ─────────────────────────────────────
# Discord OAuth2 関連定数
# ─────────────────────────────────────

DISCORD_OAUTH_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE_URL = "https://discord.com/api"

DISCORD_CLIENT_ID = settings.DISCORD_CLIENT_ID
DISCORD_CLIENT_SECRET = settings.DISCORD_CLIENT_SECRET
DISCORD_REDIRECT_URI = settings.DISCORD_REDIRECT_URI

# settings.py のスコープはここでは使わず固定でもOKだが、
# 設定値に合わせるならこうしてもよい:
DISCORD_SCOPES = settings.DISCORD_SCOPES


# ─────────────────────────────────────
# WebSocket / ダッシュボード状態管理クラス
# ─────────────────────────────────────
class DashboardState:
    def __init__(self, bot: "commands.Bot"):
        self.bot = bot
        self.websockets: Set[WebSocket] = set()

    async def register(self, websocket: WebSocket):
        await websocket.accept()
        self.websockets.add(websocket)

    async def unregister(self, websocket: WebSocket):
        if websocket in self.websockets:
            self.websockets.remove(websocket)

    async def broadcast_vc_update(self):
        """
        現在のVC状況を全WebSocketクライアントへブロードキャスト
        """
        if not self.websockets:
            return

        payload = []

        for g in self.bot.guilds:
            guild_data = {
                "id": g.id,
                "name": g.name,
                "vcs": [],
            }
            for ch in g.voice_channels:
                if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                    guild_data["vcs"].append(
                        {
                            "id": ch.id,
                            "name": ch.name,
                            "members": [m.display_name for m in ch.members],
                        }
                    )
            payload.append(guild_data)

        living_ws = set()
        for ws in list(self.websockets):
            try:
                await ws.send_json({"type": "vc_update", "data": payload})
                living_ws.add(ws)
            except Exception:
                # 送信失敗したWSは切断扱い
                pass

        self.websockets = living_ws


def create_app(bot) -> FastAPI:
    """
    Discord Bot インスタンスを受け取り、FastAPI アプリを組み立てて返す
    """
    app = FastAPI(title="VC Dashboard with Discord OAuth2")

    # セッションミドルウェア（ログイン状態の保持に必須）
    # ★ HTTPでもCookieが効くように https_only=False を指定 ★
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.DASHBOARD_SESSION_SECRET,
        session_cookie="vc_dashboard_session",
        https_only=False,
    )

    # Bot / Dashboard 状態を app.state に保持
    app.state.bot = bot
    app.state.dashboard_state = DashboardState(bot)

    dashboard_state: DashboardState = app.state.dashboard_state

    # ─────────────────────────────────
    # ユーティリティ: ログインチェック
    # ─────────────────────────────────
    def require_login(request: Request):
        """
        ログインしていなければ None を返し、
        ログインしていれば user 情報(dict)を返す
        """
        user = request.session.get("user")
        if not user:
            return None
        return user

    # ─────────────────────────────────
    # ルート: ログイン画面（Discord OAuth2 へリダイレクト）
    # ─────────────────────────────────
    @app.get("/login")
    async def login():
        """
        Discord の OAuth2 認可エンドポイントへリダイレクトする
        """
        params = {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(DISCORD_SCOPES),
        }
        url = f"{DISCORD_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        return RedirectResponse(url)

    # ─────────────────────────────────
    # ルート: ログアウト（セッション削除）
    # ─────────────────────────────────
    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/", status_code=302)

    # ─────────────────────────────────
    # ルート: OAuth2 コールバック
    # ─────────────────────────────────
    @app.get("/callback")
    async def callback(request: Request, code: str = None, error: str = None):
        """
        Discord からの認可コードを受け取り、トークンを取得してユーザー情報をセッションに保存する
        """
        print("🟡 [OAuth2] /callback に到達")
        print(f"code = {code} error = {error}")

        if error:
            return RedirectResponse("/login", status_code=302)

        if not code:
            return RedirectResponse("/login", status_code=302)

        # 認可コードをアクセストークンに交換
        data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_OAUTH_TOKEN_URL, data=data) as resp:
                token_data = await resp.json()

            print(f"🟡 token_data = {token_data}")

            access_token = token_data.get("access_token")
            token_type = token_data.get("token_type", "Bearer")

            if not access_token:
                return RedirectResponse("/login", status_code=302)

            headers = {"Authorization": f"{token_type} {access_token}"}

            # ユーザー情報取得
            async with session.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=headers) as resp:
                user_data = await resp.json()

            print(f"🟡 user_data = {user_data}")

            # 所属ギルド一覧も取得
            async with session.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=headers) as resp:
                guilds_data = await resp.json()

        # セッションに保存（最小限）
        request.session["access_token"] = access_token
        request.session["token_type"] = token_type
        request.session["user"] = {
            "id": user_data.get("id"),
            "username": user_data.get("username"),
            "discriminator": user_data.get("discriminator"),
            "global_name": user_data.get("global_name"),
        }
        request.session["guilds"] = guilds_data

        print("🟢 user データをセッション保存")

        return RedirectResponse("/", status_code=302)

    # ─────────────────────────────────
    # トップページ（ギルド一覧）
    # ─────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        # ログインチェック
        user = require_login(request)
        if not user:
            return RedirectResponse("/login", status_code=302)

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
                "user": user,
            },
        )

    # ─────────────────────────────────
    # ギルド詳細（現在のVC状況 + 履歴）
    # ─────────────────────────────────
    @app.get("/guild/{guild_id}", response_class=HTMLResponse)
    async def guild_detail(request: Request, guild_id: int):
        # ログインチェック
        user = require_login(request)
        if not user:
            return RedirectResponse("/login", status_code=302)

        guild = bot.get_guild(guild_id)
        if guild is None:
            return RedirectResponse("/", status_code=302)

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

        # DBからVC履歴を取得（最大50件）
        sessions = db_utils.get_sessions_by_guild(guild.id, limit=50)

        return templates.TemplateResponse(
            "guild.html",
            {
                "request": request,
                "guild": guild,
                "vc_list": vc_list,
                "sessions": sessions,
                "user": user,
            },
        )

    # ─────────────────────────────────
    # WebSocket: リアルタイムVC更新
    # （フロント側で ws://host:49162/ws に接続する想定）
    # ─────────────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await dashboard_state.register(ws)
        try:
            # 接続直後に一度送っておく
            await dashboard_state.broadcast_vc_update()
            while True:
                # クライアントからのメッセージは特に使わないので受信だけして捨てる
                await ws.receive_text()
        except WebSocketDisconnect:
            await dashboard_state.unregister(ws)
        except Exception:
            await dashboard_state.unregister(ws)

    # ─────────────────────────────────
    # シンプルなステータスAPI（ログイン不要でもOK）
    # ─────────────────────────────────
    @app.get("/api/status")
    async def api_status():
        return {
            "guilds": len(bot.guilds),
            "user": str(bot.user) if bot.user else None,
        }

    return app
