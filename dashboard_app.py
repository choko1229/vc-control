# dashboard_app.py

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import aiohttp
from urllib.parse import urlencode

import settings
from utils import db_utils

templates = Jinja2Templates(directory="templates")


# ===========================================================
# DashboardState（Bot側が呼び出すメソッドを保持）
# ===========================================================
class DashboardState:
    def __init__(self, bot):
        self.bot = bot

    async def broadcast_vc_update(self):
        print("[DashboardState] broadcast_vc_update() called")
        # WebSocketなどを後で実装予定
        return


# ===========================================================
# OAuth2定数
# ===========================================================
DISCORD_OAUTH_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE_URL = "https://discord.com/api"

DISCORD_CLIENT_ID = settings.DISCORD_CLIENT_ID
DISCORD_CLIENT_SECRET = settings.DISCORD_CLIENT_SECRET
DISCORD_REDIRECT_URI = settings.DISCORD_REDIRECT_URI

DISCORD_SCOPES = ["identify", "guilds"]


# ===========================================================
# FastAPI アプリ本体
# ===========================================================
def create_app(bot):
    app = FastAPI(title="VC Dashboard")

    # 静的ファイル（/static/*）
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # セッションミドルウェア（Cookie保存）
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.DASHBOARD_SESSION_SECRET,
        session_cookie="vc_session",
        max_age=60 * 60 * 24 * 7,  # 7日
    )

    # Bot / DashboardState を app.state に登録
    app.state.bot = bot
    app.state.dashboard_state = DashboardState(bot)

    # -------------------------------------------------------
    # ログイン必須デコレータ
    # -------------------------------------------------------
    def require_login(request: Request):
        user = request.session.get("user")
        print(f"🟡 [DEBUG] require_login(): user = {user}")
        return user

    # -------------------------------------------------------
    # /login
    # -------------------------------------------------------
    @app.get("/login")
    async def login():
        params = {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(DISCORD_SCOPES),
        }
        url = f"{DISCORD_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        return RedirectResponse(url)

    # -------------------------------------------------------
    # /callback
    # -------------------------------------------------------
    @app.get("/callback")
    async def callback(request: Request, code: str = None, error: str = None):
        print("🟡 [OAuth2] /callback に到達")
        print("code =", code, "error =", error)

        if error or not code:
            return RedirectResponse("/login")

        # --- 認可コードをアクセストークンに交換 ---
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

            print("🟡 token_data =", token_data)

            access_token = token_data.get("access_token")
            token_type = token_data.get("token_type", "Bearer")

            if not access_token:
                return RedirectResponse("/login")

            headers = {"Authorization": f"{token_type} {access_token}"}

            # --- ユーザー情報 ---
            async with session.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=headers) as resp:
                user_data = await resp.json()

            print("🟡 user_data =", user_data)

        # --- セッション保存 ---
        request.session["user"] = {
            "id": user_data.get("id"),
            "username": user_data.get("username"),
            "global_name": user_data.get("global_name"),
            "avatar": user_data.get("avatar"),
        }

        print("🟢 user データをセッション保存")

        return RedirectResponse("/")

    # -------------------------------------------------------
    # /
    # -------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        user = require_login(request)
        if not user:
            return RedirectResponse("/login")

        guilds = []
        try:
            for g in bot.guilds:
                vc_count = sum(len(vc.members) for vc in g.voice_channels)
                guilds.append({"id": g.id, "name": g.name, "vc_count": vc_count})
        except Exception:
            guilds = []

        return templates.TemplateResponse(
            "index.html",
            {"request": request, "user": user, "guilds": guilds},
        )

    # -------------------------------------------------------
    # /api/user（フロントエンドの初期化用）
    # -------------------------------------------------------
    @app.get("/api/user")
    async def api_user(request: Request):
        user = require_login(request)
        if not user:
            return JSONResponse({"authenticated": False})

        return JSONResponse({"authenticated": True, "user": user})

    # -------------------------------------------------------
    # /logout
    # -------------------------------------------------------
    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login")

    # -------------------------------------------------------
    # /guild/{guild_id}
    # -------------------------------------------------------
    @app.get("/guild/{guild_id}", response_class=HTMLResponse)
    async def guild_detail(request: Request, guild_id: int):
        user = require_login(request)
        if not user:
            return RedirectResponse("/login")

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return HTMLResponse("Guild not found", status_code=404)

        vc_list = [
            {
                "id": vc.id,
                "name": vc.name,
                "members": [member.display_name for member in vc.members],
            }
            for vc in guild.voice_channels
        ]

        sessions = db_utils.get_sessions_by_guild(guild_id=guild.id, limit=50)

        return templates.TemplateResponse(
            "guild.html",
            {
                "request": request,
                "user": user,
                "guild": {"id": guild.id, "name": guild.name},
                "vc_list": vc_list,
                "sessions": sessions,
            },
        )

    return app
