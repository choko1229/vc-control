# main.py

import asyncio
import discord
from discord.ext import commands
import uvicorn

import settings
from dashboard_app import create_app


intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_cogs_sync():
    print("[INFO] Loading Cogs...")
    bot.load_extension("cogs.presence")
    bot.load_extension("cogs.vc_manager")
    bot.load_extension("cogs.vc_notice")
    bot.load_extension("cogs.vc_team")
    bot.load_extension("cogs.dm_forward")
    bot.load_extension("cogs.cleaner")
    print("[INFO] Cogs Loaded Successfully.")


async def start_bot():
    await bot.start(settings.TOKEN)


async def start_dashboard():
    # create_app → DashboardState を持った FastAPI を返す
    app = create_app(bot)

    # DashboardState を Bot 側へセット
    bot.dashboard = app.state.dashboard_state

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=49162,
        log_level="info"
    )
    server = uvicorn.Server(config)

    await server.serve()


async def main_async():
    load_cogs_sync()
    await asyncio.gather(start_bot(), start_dashboard())


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Shutting down...")


if __name__ == "__main__":
    main()
