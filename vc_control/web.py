from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from vc_control.bootstrap import AppContainer
from vc_control.models import GuildConfig, OAuthProfile, SetupPayload
from vc_control.utils import format_duration, safe_int


def _sign_ws_token(secret: str, user_id: int) -> str:
    nonce = secrets.token_hex(8)
    payload = f"{user_id}:{nonce}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("utf-8")


def _verify_ws_token(secret: str, token: str) -> int | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user_id_text, nonce, signature = decoded.split(":")
    except Exception:
        return None
    payload = f"{user_id_text}:{nonce}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return safe_int(user_id_text)


def _build_avatar_url(user: dict[str, Any]) -> str | None:
    avatar = user.get("avatar")
    if not avatar:
        return None
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"


def _current_profile(request: Request) -> OAuthProfile | None:
    raw = request.session.get("oauth_profile")
    if not isinstance(raw, dict):
        return None
    return OAuthProfile.from_session(raw)


async def _require_profile(request: Request) -> OAuthProfile:
    profile = _current_profile(request)
    if profile is None:
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    return profile


async def _require_admin(request: Request, container: AppContainer) -> OAuthProfile:
    profile = await _require_profile(request)
    settings = await container.config_repo.get_runtime_settings()
    if safe_int(settings.get("owner_user_id")) != profile.user_id:
        raise HTTPException(status_code=403, detail="Bot Ownerのみ利用できます。")
    return profile


def _guild_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("guild_name") or "").lower()


def _serialize_guild_channels(container: AppContainer, guild_id: int) -> dict[str, list[dict[str, Any]]]:
    if container.bot is None:
        return {"categories": [], "voice_channels": [], "text_channels": []}
    guild = container.bot.get_guild(guild_id)
    if guild is None:
        return {"categories": [], "voice_channels": [], "text_channels": []}
    return {
        "categories": [{"id": channel.id, "name": channel.name} for channel in sorted(guild.categories, key=lambda item: item.position)],
        "voice_channels": [{"id": channel.id, "name": channel.name} for channel in sorted(guild.voice_channels, key=lambda item: item.position)],
        "text_channels": [{"id": channel.id, "name": channel.name} for channel in sorted(guild.text_channels, key=lambda item: item.position)],
    }


async def _fetch_runtime_settings(container: AppContainer) -> dict[str, str]:
    return await container.config_repo.get_runtime_settings()


def _build_auth_url(settings: dict[str, str], state: str) -> str:
    params = {
        "client_id": settings.get("client_id", ""),
        "redirect_uri": settings.get("redirect_uri", ""),
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    return f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"


async def _exchange_code(settings: dict[str, str], code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.get("client_id", ""),
                "client_secret": settings.get("client_secret", ""),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.get("redirect_uri", ""),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def _fetch_discord_profile(access_token: str) -> OAuthProfile:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        user_response = await client.get("https://discord.com/api/users/@me", headers=headers)
        guilds_response = await client.get("https://discord.com/api/users/@me/guilds", headers=headers)
        user_response.raise_for_status()
        guilds_response.raise_for_status()
        user_payload = user_response.json()
        guilds_payload = guilds_response.json()
    return OAuthProfile(
        user_id=int(user_payload["id"]),
        username=str(user_payload["username"]),
        global_name=user_payload.get("global_name"),
        avatar_url=_build_avatar_url(user_payload),
        guilds=guilds_payload,
    )


def create_app(container: AppContainer) -> FastAPI:
    templates = Jinja2Templates(directory=str(container.root_dir / "vc_control" / "templates"))
    app = FastAPI(title="VC Control Dashboard")
    session_secret = os.environ.get("SESSION_SECRET_FALLBACK", secrets.token_urlsafe(32))
    app.add_middleware(SessionMiddleware, secret_key=session_secret, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(container.root_dir / "vc_control" / "static")), name="static")
    app.state.container = container
    app.state.templates = templates
    app.state.ws_secret = session_secret

    def render(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
        profile = _current_profile(request)
        base_context = {
            "request": request,
            "current_user": profile,
            "app_version": "1.0.0",
        }
        base_context.update(context)
        return templates.TemplateResponse(template_name, base_context, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse | RedirectResponse:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        if _current_profile(request) is None:
            return RedirectResponse("/login", status_code=302)
        return RedirectResponse("/dashboard/me", status_code=302)

    @app.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request) -> HTMLResponse:
        if await container.config_repo.is_setup_complete():
            raise HTTPException(status_code=404, detail="初回セットアップは無効です。")
        return render(request, "setup.html", {"title": "初回セットアップ"})

    @app.post("/setup")
    async def submit_setup(request: Request) -> RedirectResponse:
        if await container.config_repo.is_setup_complete():
            raise HTTPException(status_code=404, detail="初回セットアップは無効です。")
        form = await request.form()
        expected_password = os.environ.get("SETUP_PASSWORD", "")
        payload = SetupPayload(
            setup_password=str(form.get("setup_password", "")),
            bot_token=str(form.get("bot_token", "")).strip(),
            client_id=str(form.get("client_id", "")).strip(),
            client_secret=str(form.get("client_secret", "")).strip(),
            redirect_uri=str(form.get("redirect_uri", "")).strip(),
            base_url=str(form.get("base_url", "")).strip(),
            owner_user_id=safe_int(form.get("owner_user_id")),
            dashboard_host=str(form.get("dashboard_host", "127.0.0.1")).strip(),
            dashboard_port=safe_int(form.get("dashboard_port"), 8000),
        )
        if not expected_password or payload.setup_password != expected_password:
            raise HTTPException(status_code=403, detail="セットアップパスワードが正しくありません。")
        await container.config_repo.save_initial_setup(payload, secrets.token_urlsafe(32))
        return RedirectResponse("/login?setup=1", status_code=302)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        if _current_profile(request) is not None:
            return RedirectResponse("/dashboard/me", status_code=302)
        settings = await _fetch_runtime_settings(container)
        error = None
        if not settings.get("client_id") or not settings.get("client_secret"):
            error = "OAuth設定が未完了です。"
        elif request.query_params.get("oauth_error"):
            error = "OAuth設定が不足しているためログインを開始できません。"
        return render(request, "login.html", {"title": "ログイン", "error": error})

    @app.get("/auth/login")
    async def login(request: Request) -> RedirectResponse:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        settings = await _fetch_runtime_settings(container)
        if not settings.get("client_id") or not settings.get("client_secret"):
            return RedirectResponse("/login?oauth_error=1", status_code=302)
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        return RedirectResponse(_build_auth_url(settings, state), status_code=302)

    @app.get("/auth/callback")
    async def auth_callback(request: Request, code: str | None = None, state: str | None = None) -> RedirectResponse:
        expected_state = request.session.get("oauth_state")
        if not code or not state or not expected_state or expected_state != state:
            raise HTTPException(status_code=400, detail="OAuth状態検証に失敗しました。")
        settings = await _fetch_runtime_settings(container)
        try:
            token_payload = await _exchange_code(settings, code)
            profile = await _fetch_discord_profile(token_payload["access_token"])
        except httpx.HTTPError as exc:
            container.logger.exception("OAuth認証に失敗しました")
            raise HTTPException(status_code=502, detail="Discord OAuthに失敗しました。") from exc
        request.session["oauth_profile"] = profile.to_session()
        request.session.pop("oauth_state", None)
        return RedirectResponse("/dashboard/me", status_code=302)

    @app.get("/auth/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/dashboard/me", response_class=HTMLResponse)
    async def dashboard_me(request: Request) -> HTMLResponse:
        profile = await _require_profile(request)
        settings = await _fetch_runtime_settings(container)
        is_admin = safe_int(settings.get("owner_user_id")) == profile.user_id
        sessions = await container.session_manager.list_accessible_sessions(profile.user_id)
        summary = await container.stats_repo.get_user_period_summary(profile.user_id, "all")
        guild_breakdown = await container.stats_repo.get_user_guild_breakdown(profile.user_id, "all")
        return render(
            request,
            "dashboard.html",
            {
                "title": "マイダッシュボード",
                "sessions": sessions,
                "summary": summary,
                "guild_breakdown": guild_breakdown,
                "is_admin": is_admin,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/voice/{guild_id}/{root_channel_id}", response_class=HTMLResponse)
    async def voice_dashboard(request: Request, guild_id: int, root_channel_id: int) -> HTMLResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_view_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="閲覧権限がありません。")
        can_edit = await container.session_manager.can_edit_session(session, profile.user_id)
        voice_channel = container.session_manager.resolve_voice_channel(root_channel_id)
        return render(
            request,
            "voice.html",
            {
                "title": "VC管理",
                "page_name": "voice",
                "guild_id": guild_id,
                "root_channel_id": root_channel_id,
                "session": session.to_payload(),
                "can_edit": can_edit,
                "can_assign_others": await container.session_manager.can_assign_others(session, profile.user_id),
                "voice_channel": voice_channel,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/stats/me", response_class=HTMLResponse)
    async def my_stats(request: Request, period: str = "all", guild_id: int | None = None) -> HTMLResponse:
        profile = await _require_profile(request)
        summary = await container.stats_repo.get_user_period_summary(profile.user_id, period)
        breakdown = await container.stats_repo.get_user_guild_breakdown(profile.user_id, period)
        known_guilds = await container.stats_repo.get_known_guilds_for_user(profile.user_id)
        daily_chart = await container.stats_repo.get_user_daily_chart(profile.user_id, guild_id)
        hourly_heatmap = await container.stats_repo.get_user_hourly_heatmap(profile.user_id, guild_id)
        return render(
            request,
            "stats_me.html",
            {
                "title": "自分の通話時間",
                "period": period,
                "selected_guild_id": guild_id,
                "summary": summary,
                "breakdown": breakdown,
                "known_guilds": known_guilds,
                "daily_chart": daily_chart,
                "hourly_heatmap": hourly_heatmap,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/rankings", response_class=HTMLResponse)
    async def rankings(request: Request, period: str = "all", guild_id: int | None = None) -> HTMLResponse:
        profile = await _require_profile(request)
        rankings_data = await container.stats_repo.get_rankings(period=period, guild_id=guild_id, limit=100)
        known_guilds = await container.stats_repo.get_known_guilds_for_user(profile.user_id)
        return render(
            request,
            "rankings.html",
            {
                "title": "ランキング",
                "period": period,
                "selected_guild_id": guild_id,
                "rankings": rankings_data,
                "known_guilds": known_guilds,
                "format_duration": format_duration,
            },
        )

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request, guild_id: int | None = None, page: int = 1) -> HTMLResponse:
        profile = await _require_admin(request, container)
        settings = await _fetch_runtime_settings(container)
        guild_configs = await container.config_repo.list_guild_configs()
        bot_guilds = [
            {"id": guild.id, "name": guild.name}
            for guild in (container.bot.guilds if container.bot else [])
        ]
        bot_guilds.sort(key=_guild_sort_key)
        selected_guild_id = guild_id or (bot_guilds[0]["id"] if bot_guilds else None)
        selected_config = next((config for config in guild_configs if config.guild_id == selected_guild_id), None)
        channel_catalog = _serialize_guild_channels(container, selected_guild_id) if selected_guild_id else {"categories": [], "voice_channels": [], "text_channels": []}
        error_logs, total_logs = await container.config_repo.get_error_logs(page=page, per_page=25)
        recent_sessions = await container.stats_repo.get_recent_sessions(limit=20)
        return render(
            request,
            "admin.html",
            {
                "title": "アドミン管理",
                "profile": profile,
                "settings": settings,
                "bot_guilds": bot_guilds,
                "selected_guild_id": selected_guild_id,
                "selected_config": selected_config,
                "channel_catalog": channel_catalog,
                "recent_sessions": recent_sessions,
                "error_logs": error_logs,
                "page": page,
                "total_logs": total_logs,
                "format_duration": format_duration,
            },
        )

    @app.post("/admin/settings")
    async def update_admin_settings(request: Request) -> RedirectResponse:
        await _require_admin(request, container)
        form = await request.form()
        plain_values = {
            "client_id": str(form.get("client_id", "")).strip(),
            "redirect_uri": str(form.get("redirect_uri", "")).strip(),
            "base_url": str(form.get("base_url", "")).strip(),
            "owner_user_id": str(safe_int(form.get("owner_user_id"))),
            "dashboard_host": str(form.get("dashboard_host", "127.0.0.1")).strip(),
            "dashboard_port": str(safe_int(form.get("dashboard_port"), 8000)),
        }
        secure_values = {
            "bot_token": str(form.get("bot_token", "")).strip(),
            "client_secret": str(form.get("client_secret", "")).strip(),
        }
        await container.config_repo.update_runtime_settings(plain_values, secure_values)
        return RedirectResponse("/admin?saved=1", status_code=302)

    @app.post("/admin/guilds/{guild_id}")
    async def update_guild_config(request: Request, guild_id: int) -> RedirectResponse:
        await _require_admin(request, container)
        form = await request.form()
        current = await container.config_repo.get_guild_config(guild_id)
        guild = container.bot.get_guild(guild_id) if container.bot else None
        guild_name = current.guild_name if current else (guild.name if guild else str(guild_id))
        config = GuildConfig(
            guild_id=guild_id,
            guild_name=guild_name,
            managed_category_id=safe_int(form.get("managed_category_id")) or None,
            base_voice_channel_id=safe_int(form.get("base_voice_channel_id")) or None,
            notification_channel_id=safe_int(form.get("notification_channel_id")) or None,
            first_empty_notice_sec=safe_int(form.get("first_empty_notice_sec"), 30),
            final_delete_sec=safe_int(form.get("final_delete_sec"), 90),
            team_mode=str(form.get("team_mode", "custom")).strip(),
            team_names=[name.strip() for name in str(form.get("team_names", "A,B,C,D")).split(",") if name.strip()],
            enabled=str(form.get("enabled", "")) == "on",
        )
        await container.config_repo.upsert_guild_config(config)
        await container.session_manager.refresh_guild_configs()
        return RedirectResponse(f"/admin?guild_id={guild_id}&saved=1", status_code=302)

    @app.get("/api/ws-token")
    async def ws_token(request: Request) -> JSONResponse:
        profile = await _require_profile(request)
        return JSONResponse({"token": _sign_ws_token(app.state.ws_secret, profile.user_id)})

    @app.get("/api/voice/{guild_id}/{root_channel_id}")
    async def session_payload(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_view_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="閲覧権限がありません。")
        payload = session.to_payload()
        payload["can_edit"] = await container.session_manager.can_edit_session(session, profile.user_id)
        return JSONResponse(payload)

    @app.post("/api/voice/{guild_id}/{root_channel_id}/settings")
    async def api_update_voice_settings(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_edit_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="変更権限がありません。")
        payload = await request.json()
        await container.session_manager.update_voice_settings(
            root_channel_id=root_channel_id,
            name=str(payload.get("name")).strip() if payload.get("name") else None,
            user_limit=safe_int(payload.get("user_limit")) if payload.get("user_limit") is not None else None,
            bitrate=safe_int(payload.get("bitrate")) if payload.get("bitrate") is not None else None,
        )
        return JSONResponse({"ok": True})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/member-state")
    async def api_member_state(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_edit_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="変更権限がありません。")
        payload = await request.json()
        await container.session_manager.set_member_server_state(
            root_channel_id=root_channel_id,
            target_user_id=safe_int(payload.get("user_id")),
            mute=payload.get("mute"),
            deafen=payload.get("deafen"),
        )
        return JSONResponse({"ok": True})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/assign")
    async def api_team_assign(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        payload = await request.json()
        try:
            message = await container.session_manager.assign_team(
                root_channel_id,
                profile.user_id,
                safe_int(payload.get("user_id")),
                payload.get("team_name"),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "message": message})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/split")
    async def api_team_split(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        try:
            result = await container.session_manager.split_teams(root_channel_id, profile.user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/assemble")
    async def api_team_assemble(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        try:
            result = await container.session_manager.assemble_teams(root_channel_id, profile.user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/recall")
    async def api_team_recall(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        session = container.session_manager.get_session_by_root(root_channel_id)
        if session is None or session.guild_id != guild_id:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        payload = await request.json()
        try:
            result = await container.session_manager.recall_member(root_channel_id, profile.user_id, safe_int(payload.get("user_id")))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str, scopes: str = "global") -> None:
        user_id = _verify_ws_token(app.state.ws_secret, token)
        if user_id is None:
            await websocket.close(code=4001)
            return
        requested_scopes = [item.strip() for item in scopes.split(",") if item.strip()]
        allowed_scopes: list[str] = []
        for scope in requested_scopes:
            if scope == "global":
                allowed_scopes.append(scope)
                continue
            if scope == f"user:{user_id}":
                allowed_scopes.append(scope)
                continue
            if scope.startswith("session:"):
                root_id = safe_int(scope.split(":", 1)[1])
                session = container.session_manager.get_session_by_root(root_id)
                if session and await container.session_manager.can_view_session(session, user_id):
                    allowed_scopes.append(scope)
                continue
            if scope.startswith("guild:"):
                guild_id = safe_int(scope.split(":", 1)[1])
                if await container.session_manager.is_guild_admin(guild_id, user_id):
                    allowed_scopes.append(scope)
                    continue
                for session in container.session_manager.list_sessions():
                    if session.guild_id == guild_id and await container.session_manager.can_view_session(session, user_id):
                        allowed_scopes.append(scope)
                        break
        if not allowed_scopes:
            await websocket.close(code=4003)
            return
        await container.websocket_hub.connect(websocket, allowed_scopes)
        try:
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            await container.websocket_hub.disconnect(websocket)
        except Exception:
            await container.websocket_hub.disconnect(websocket)

    return app
