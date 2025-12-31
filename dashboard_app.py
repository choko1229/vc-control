# dashboard_app.py

import discord
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

    async def fetch_member(guild: discord.Guild, user_id: int):
        member = guild.get_member(user_id)
        if member:
            return member
        try:
            return await guild.fetch_member(user_id)
        except Exception:
            return None

    def build_manage_url(guild_id: int, vc_id: int) -> str:
        base = settings.DASHBOARD_BASE_URL.rstrip("/") if settings.DASHBOARD_BASE_URL else ""
        if base:
            return f"{base}/guild/{guild_id}/vc/{vc_id}"
        return f"/guild/{guild_id}/vc/{vc_id}"

    def get_session_for(vc_id: int):
        if not bot:
            return None
        notice_cog = bot.get_cog("VCNotice")
        if notice_cog and hasattr(notice_cog, "sessions"):
            return notice_cog.sessions.get(vc_id)
        return None

    def can_manage(member: discord.Member | None, starter_id: int | None):
        if member is None:
            return False
        if member.guild_permissions.administrator:
            return True
        return starter_id is not None and member.id == starter_id

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

        member = await fetch_member(guild, int(user["id"])) if guild else None
        notice_sessions = (
            bot.get_cog("VCNotice").sessions if bot and bot.get_cog("VCNotice") else {}
        )

        vc_list = []
        for vc in guild.voice_channels:
            session = notice_sessions.get(vc.id, {})
            starter_id = session.get("starter_id") if isinstance(session, dict) else None
            vc_list.append(
                {
                    "id": vc.id,
                    "name": vc.name,
                    "members": [member.display_name for member in vc.members],
                    "manage_url": build_manage_url(guild.id, vc.id),
                    "starter_id": starter_id,
                    "can_manage": can_manage(member, starter_id),
                }
            )

        sessions = db_utils.get_sessions_by_guild(guild_id=guild.id, limit=50)

        return templates.TemplateResponse(
            "guild.html",
            {
                "request": request,
                "user": user,
                "guild": {"id": guild.id, "name": guild.name},
                "is_admin": bool(member and member.guild_permissions.administrator),
                "vc_list": vc_list,
                "sessions": sessions,
            },
        )

    # -------------------------------------------------------
    # /guild/{guild_id}/vc/{vc_id}
    # -------------------------------------------------------
    @app.get("/guild/{guild_id}/vc/{vc_id}", response_class=HTMLResponse)
    async def vc_manage(request: Request, guild_id: int, vc_id: int):
        user = require_login(request)
        if not user:
            return RedirectResponse("/login")

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return HTMLResponse("Guild not found", status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not isinstance(vc, discord.VoiceChannel):
            return HTMLResponse("VC not found", status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        session = get_session_for(vc.id) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None
        allowed = can_manage(member, starter_id)

        if not allowed:
            return HTMLResponse("管理権限がありません。", status_code=403)

        starter_name = None
        participants = session.get("participants") if isinstance(session, dict) else None
        if participants and starter_id in participants:
            starter_name = participants[starter_id].get("name")

        return templates.TemplateResponse(
            "vc_manage.html",
            {
                "request": request,
                "user": user,
                "guild": {"id": guild.id, "name": guild.name},
                "vc": {
                    "id": vc.id,
                    "name": vc.name,
                    "user_limit": vc.user_limit or 0,
                    "bitrate": vc.bitrate,
                    "starter_id": starter_id,
                    "starter_name": starter_name,
                    "manage_url": build_manage_url(guild.id, vc.id),
                },
                "limits": {"bitrate": guild.bitrate_limit},
                "is_admin": bool(member and member.guild_permissions.administrator),
                "is_owner": bool(member and starter_id and member.id == starter_id),
            },
        )

    # -------------------------------------------------------
    # /guild/{guild_id}/vc/{vc_id}/update
    # -------------------------------------------------------
    @app.post("/guild/{guild_id}/vc/{vc_id}/update")
    async def update_vc(request: Request, guild_id: int, vc_id: int):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return JSONResponse({"ok": False, "error": "guild_not_found"}, status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not isinstance(vc, discord.VoiceChannel):
            return JSONResponse({"ok": False, "error": "vc_not_found"}, status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        session = get_session_for(vc.id) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None

        if not can_manage(member, starter_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        payload = await request.json()
        updates = {}

        name = payload.get("name")
        if name:
            updates["name"] = str(name)[:100]

        if "user_limit" in payload:
            try:
                limit = int(payload.get("user_limit", 0))
            except (TypeError, ValueError):
                limit = vc.user_limit or 0
            limit = max(0, min(limit, 99))
            updates["user_limit"] = limit

        if "bitrate" in payload:
            try:
                bitrate = int(payload.get("bitrate", vc.bitrate))
            except (TypeError, ValueError):
                bitrate = vc.bitrate
            bitrate = max(8000, min(bitrate, guild.bitrate_limit))
            updates["bitrate"] = bitrate

        if updates:
            try:
                await vc.edit(**updates, reason="Dashboard VC管理")
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        return JSONResponse({"ok": True, "updates": updates})

    return app
