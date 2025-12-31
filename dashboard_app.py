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
from utils.voice_utils import active_seconds
from datetime import datetime, timedelta

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

    def is_manageable_vc(vc: discord.abc.GuildChannel) -> bool:
        return (
            isinstance(vc, discord.VoiceChannel)
            and vc.category
            and vc.category.id == settings.VC_CATEGORY_ID
            and vc.id != settings.BASE_VC_ID
        )

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

    def ensure_session(vc: discord.VoiceChannel):
        notice_cog = bot.get_cog("VCNotice") if bot else None
        if not notice_cog:
            return None
        return notice_cog.ensure_session_by_voice(vc, discord.utils.utcnow())

    def team_cog():
        return bot.get_cog("VCTeam") if bot else None

    def base_session_for(channel: discord.abc.GuildChannel | None):
        notice_cog = bot.get_cog("VCNotice") if bot else None
        if not notice_cog or not channel:
            return None
        if hasattr(notice_cog, "base_session_for_channel"):
            return notice_cog.base_session_for_channel(channel)
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
    # /api/usage（利用統計）
    # -------------------------------------------------------
    @app.get("/api/usage")
    async def api_usage(request: Request):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        days = 7
        try:
            usage = db_utils.get_usage_for_user(int(user["id"]), days=days)
        except Exception as e:
            print(f"[/api/usage] failed to load usage: {e}")
            # Return an empty usage snapshot to avoid dashboard breakage.
            usage = {
                "total_seconds": 0,
                "daily": [
                    {
                        "label": f"{day.month}/{day.day}",
                        "seconds": 0,
                    }
                    for day in [
                        (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
                        for i in range(days)
                    ]
                ],
                "hourly": [0 for _ in range(24)],
                "error": str(e),
            }

        return JSONResponse({"ok": True, **usage})

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
            if not is_manageable_vc(vc):
                continue
            session = notice_sessions.get(vc.id, {})
            starter_id = session.get("starter_id") if isinstance(session, dict) else None
            starter_name = None
            participants = session.get("participants") if isinstance(session, dict) else None
            if participants and starter_id in participants:
                starter_name = participants[starter_id].get("name")
            vc_list.append(
                {
                    "id": vc.id,
                    "name": vc.name,
                    "members": [member.display_name for member in vc.members],
                    "manage_url": build_manage_url(guild.id, vc.id),
                    "starter_id": starter_id,
                    "starter_name": starter_name,
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
        if not is_manageable_vc(vc):
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
    # /guild/{guild_id}/vc/{vc_id}/state
    # -------------------------------------------------------
    @app.get("/guild/{guild_id}/vc/{vc_id}/state")
    async def vc_state(request: Request, guild_id: int, vc_id: int):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return JSONResponse({"ok": False, "error": "guild_not_found"}, status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not is_manageable_vc(vc):
            return JSONResponse({"ok": False, "error": "vc_not_found"}, status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        session = get_session_for(vc.id) or ensure_session(vc) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None

        if not can_manage(member, starter_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        participants = session.get("participants", {}) if isinstance(session, dict) else {}
        now = discord.utils.utcnow()
        members = []
        raw_members = list(vc.members)
        for ch_id in session.get("team_channels", {}).values() if isinstance(session, dict) else []:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.VoiceChannel):
                raw_members.extend(ch.members)

        seen = set()
        for m in raw_members:
            if m.id in seen:
                continue
            seen.add(m.id)
            pdata = participants.get(m.id) or {}
            joined_at = pdata.get("joined_at")
            members.append(
                {
                    "id": m.id,
                    "name": m.display_name,
                    "avatar": str(m.display_avatar.url),
                    "team": pdata.get("team"),
                    "connected_seconds": active_seconds(pdata, now=lambda: now),
                    "joined_at": joined_at.isoformat() if hasattr(joined_at, "isoformat") else None,
                    "server_mute": bool(m.voice and m.voice.mute),
                    "server_deaf": bool(m.voice and m.voice.deaf),
                    "self_mute": bool(m.voice and m.voice.self_mute),
                    "self_deaf": bool(m.voice and m.voice.self_deaf),
                }
            )

        return JSONResponse(
            {
                "ok": True,
                "members": members,
                "starter_id": starter_id,
                "team_channels": session.get("team_channels", {}),
            }
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
        if not is_manageable_vc(vc):
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

    # -------------------------------------------------------
    # /guild/{guild_id}/vc/{vc_id}/member/{user_id}/update
    # -------------------------------------------------------
    @app.post("/guild/{guild_id}/vc/{vc_id}/member/{user_id}/update")
    async def update_member_state(
        request: Request, guild_id: int, vc_id: int, user_id: int
    ):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return JSONResponse({"ok": False, "error": "guild_not_found"}, status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not is_manageable_vc(vc):
            return JSONResponse({"ok": False, "error": "vc_not_found"}, status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        target = await fetch_member(guild, int(user_id))
        session = get_session_for(vc.id) or ensure_session(vc) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None

        if isinstance(session, dict):
            session.setdefault("team_channels", {})
            # カテゴリ内にある派生VCを事前に復元し、許可チャンネルを広げる
            if not session["team_channels"] and vc.category:
                prefix = f"{vc.name}-"
                for ch in vc.category.voice_channels:
                    if ch.name.startswith(prefix):
                        suffix = ch.name[len(prefix) :].strip()
                        if suffix:
                            session["team_channels"].setdefault(suffix, ch.id)

        if not can_manage(member, starter_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        target_channel = target.voice.channel if target and target.voice else None
        if not target_channel:
            return JSONResponse({"ok": False, "error": "member_not_in_vc"}, status_code=404)

        allowed_channels = {vc.id}
        if isinstance(session, dict):
            allowed_channels.update(session.get("team_channels", {}).values())

        # 失われたセッション情報や名前変更があっても、同一カテゴリの派生VCは許可する
        same_category = target_channel.category and target_channel.category.id == vc.category.id
        name_matches = target_channel.name.startswith(f"{vc.name}-") if target_channel.name else False
        base_matches = base_session_for(target_channel) == vc.id

        if target_channel.id not in allowed_channels and not (same_category and (name_matches or base_matches)):
            return JSONResponse({"ok": False, "error": "member_not_in_vc"}, status_code=404)

        if target_channel.id not in allowed_channels and isinstance(session, dict):
            session.setdefault("team_channels", {})
            if name_matches:
                suffix = target_channel.name[len(vc.name) + 1 :].strip()
                if suffix:
                    session["team_channels"].setdefault(suffix, target_channel.id)

        payload = await request.json()
        updates = {}
        if "mute" in payload:
            updates["mute"] = bool(payload.get("mute"))
        if "deaf" in payload:
            updates["deafen"] = bool(payload.get("deaf"))

        if updates:
            try:
                await target.edit(**updates, reason="Dashboard メンバー制御")
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        if "team" in payload:
            team_value = payload.get("team")
            team_controller = team_cog()
            if team_value in {"A", "B", "C", "D"}:
                if team_controller:
                    team_controller._assign_team(vc, target, str(team_value))
                elif isinstance(session, dict):
                    parts = session.setdefault("participants", {})
                    info = parts.get(target.id)
                    if info is None:
                        info = {
                            "name": target.display_name,
                            "total_sec": 0,
                            "joined_at": discord.utils.utcnow(),
                            "team": None,
                        }
                        parts[target.id] = info
                    info["team"] = str(team_value)
                    info["name"] = target.display_name
            elif isinstance(session, dict):
                parts = session.get("participants", {})
                if target.id in parts:
                    parts[target.id]["team"] = None

        return JSONResponse({"ok": True})

    # -------------------------------------------------------
    # /guild/{guild_id}/vc/{vc_id}/teams/split
    # /guild/{guild_id}/vc/{vc_id}/teams/gather
    # -------------------------------------------------------
    @app.post("/guild/{guild_id}/vc/{vc_id}/teams/split")
    async def split_teams_endpoint(request: Request, guild_id: int, vc_id: int):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return JSONResponse({"ok": False, "error": "guild_not_found"}, status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not is_manageable_vc(vc):
            return JSONResponse({"ok": False, "error": "vc_not_found"}, status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        session = get_session_for(vc.id) or ensure_session(vc) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None

        if not can_manage(member, starter_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        controller = team_cog()
        if not controller:
            return JSONResponse({"ok": False, "error": "team_cog_missing"}, status_code=500)

        err = await controller.split_teams(vc, starter_id)
        if err:
            return JSONResponse({"ok": False, "error": err}, status_code=400)

        return JSONResponse({"ok": True})

    @app.post("/guild/{guild_id}/vc/{vc_id}/teams/gather")
    async def gather_teams_endpoint(request: Request, guild_id: int, vc_id: int):
        user = require_login(request)
        if not user:
            return JSONResponse({"ok": False, "error": "auth_required"}, status_code=401)

        guild = bot.get_guild(int(guild_id)) if bot else None
        if not guild:
            return JSONResponse({"ok": False, "error": "guild_not_found"}, status_code=404)

        vc = guild.get_channel(int(vc_id))
        if not is_manageable_vc(vc):
            return JSONResponse({"ok": False, "error": "vc_not_found"}, status_code=404)

        member = await fetch_member(guild, int(user["id"]))
        session = get_session_for(vc.id) or ensure_session(vc) or {}
        starter_id = session.get("starter_id") if isinstance(session, dict) else None

        if not can_manage(member, starter_id):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        controller = team_cog()
        if not controller:
            return JSONResponse({"ok": False, "error": "team_cog_missing"}, status_code=500)

        err = await controller.gather_teams(vc)
        if err:
            return JSONResponse({"ok": False, "error": err}, status_code=400)

        return JSONResponse({"ok": True})

    return app
