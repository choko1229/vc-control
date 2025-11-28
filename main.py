# main.py

import asyncio
import discord
from discord.ext import commands
import uvicorn

import settings
from dashboard_app import create_app, DashboardState


# ─────────────────────────────────────
# Bot 初期化
# ─────────────────────────────────────
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────
# Cog のロード（同期）
# ─────────────────────────────────────
def load_cogs_sync():
    print("[INFO] Loading Cogs...")
    bot.load_extension("cogs.presence")
    bot.load_extension("cogs.vc_manager")
    bot.load_extension("cogs.vc_notice")
    bot.load_extension("cogs.dm_forward")
    bot.load_extension("cogs.cleaner")
    print("[INFO] Cogs Loaded Successfully.")


# ─────────────────────────────────────
# Bot 起動
# ─────────────────────────────────────
async def start_bot():
    await bot.start(settings.TOKEN)


# ─────────────────────────────────────
# FastAPI ダッシュボード起動
# ─────────────────────────────────────
async def start_dashboard(dashboard_state: DashboardState):
    """
    FastAPI + Uvicorn を Discord Bot と同じイベントループで動かす。
    """
    app = create_app(bot, dashboard_state)

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
    # ★ Cog ロード
    load_cogs_sync()

    # ★ ダッシュボード用状態オブジェクトを作成
    dashboard_state = DashboardState()
    # Cogs から self.bot.dashboard.broadcast_vc_update(...) で叩けるようにする
    bot.dashboard = dashboard_state

    await asyncio.gather(
        start_bot(),
        start_dashboard(dashboard_state)
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
