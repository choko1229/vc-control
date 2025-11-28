# main.py

import asyncio
import discord
from discord.ext import commands
import uvicorn

import settings
from dashboard_app import create_app


# ─────────────────────────────────────
# Bot 初期化
# ─────────────────────────────────────
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────
# Cog のロード（同期で行う）
# ─────────────────────────────────────
def load_cogs_sync():
    bot.load_extension("cogs.presence")
    bot.load_extension("cogs.vc_manager")
    bot.load_extension("cogs.vc_notice")
    bot.load_extension("cogs.dm_forward")
    bot.load_extension("cogs.cleaner")


# ─────────────────────────────────────
# Bot 起動
# ─────────────────────────────────────
async def start_bot():
    await bot.start(settings.TOKEN)


# ─────────────────────────────────────
# FastAPI ダッシュボード起動
# ─────────────────────────────────────
async def start_dashboard():
    app = create_app(bot)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=49162,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


# ─────────────────────────────────────
# BotとWebサーバーを同時起動
# ─────────────────────────────────────
async def main_async():
    # ★ bot.start() の前に必ず Cog をロードする ★
    load_cogs_sync()

    await asyncio.gather(
        start_bot(),
        start_dashboard()
    )


# ─────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────
def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Shutting down...")


if __name__ == "__main__":
    main()
