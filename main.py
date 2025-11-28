import discord
from discord.ext import commands
import asyncio
import settings

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def load_cogs():
    """Cog ロード"""
    await bot.load_extension("cogs.presence")
    await bot.load_extension("cogs.vc_manager")
    await bot.load_extension("cogs.vc_notice")
    await bot.load_extension("cogs.dm_forward")
    await bot.load_extension("cogs.cleaner")


@bot.event
async def on_ready():
    print(f"Bot起動成功: {bot.user} (ID: {bot.user.id})")


async def start_bot():
    async with bot:
        await load_cogs()
        await bot.start(settings.TOKEN)


def main():
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()
