# utils/discord_oauth.py

import aiohttp
import settings


TOKEN_URL = "https://discord.com/api/oauth2/token"
USER_URL = "https://discord.com/api/users/@me"


async def exchange_code(code: str):
    """
    OAuth2 code → access_token 交換
    """
    data = {
        "client_id": settings.OAUTH2_CLIENT_ID,
        "client_secret": settings.OAUTH2_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.OAUTH2_REDIRECT_URI,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with aiohttp.ClientSession() as session:
        async with session.post(TOKEN_URL, data=data, headers=headers) as res:
            return await res.json()


async def fetch_user_info(access_token: str):
    """
    アクセストークンを使って Discord ユーザー情報を取得する
    """
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(USER_URL, headers=headers) as res:
            return await res.json()
