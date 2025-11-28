# utils/oauth_utils.py

import aiohttp
import settings

DISCORD_API_BASE = "https://discord.com/api"


def oauth_login_url():
    scope = "%20".join(settings.OAUTH2_SCOPES)
    return (
        f"{DISCORD_API_BASE}/oauth2/authorize"
        f"?client_id={settings.OAUTH2_CLIENT_ID}"
        f"&redirect_uri={settings.OAUTH2_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
    )


async def exchange_code(code: str):
    """
    Discord OAuth2 の code を access_token に交換
    """
    data = {
        "client_id": settings.OAUTH2_CLIENT_ID,
        "client_secret": settings.OAUTH2_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.OAUTH2_REDIRECT_URI,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            return await resp.json()


async def get_user_info(access_token: str):
    """
    OAuth2で取得したユーザー情報を返す
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{DISCORD_API_BASE}/users/@me", headers=headers) as resp:
            return await resp.json()


async def get_user_guilds(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers) as resp:
            return await resp.json()
