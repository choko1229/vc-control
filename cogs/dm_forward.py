import discord
from discord.ext import commands
import settings


class DMForward(commands.Cog):
    """VCテキストでの @メンション を対象ユーザーのDMへ転送"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def extract_text(self, message: discord.Message) -> str:
        text = message.content or ""
        for u in message.mentions:
            text = text.replace(f"<@{u.id}>", "").replace(f"<@!{u.id}>", "")
        return " ".join(text.split())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        ch = message.channel
        # VCのテキスト欄のみ（必要なら BASE VC 除外もここで可能）
        if not isinstance(ch, discord.VoiceChannel):
            return
        if ch.category is None or ch.category.id != settings.VC_CATEGORY_ID:
            return

        # @everyone/@here は警告のみ
        if message.mention_everyone:
            try:
                await ch.send("⚠️ `@everyone` / `@here` はDM転送されません。")
            except Exception:
                pass
            return

        targets = [m for m in message.mentions if not m.bot]
        if not targets:
            return

        extra = self.extract_text(message)

        for target in targets:
            embed = discord.Embed(
                title=f"🔔 {message.author.display_name}がVCであなたを呼んでいます。",
                description=f"{message.author.display_name} さんが **{ch.name}** であなたをメンションしました。",
                color=0x5865F2,
            )

            if extra:
                embed.add_field(name="メッセージ内容", value=extra, inline=False)

            embed.add_field(name="リンク", value=f"[ジャンプ]({message.jump_url})")

            try:
                await target.send(embed=embed)
            except Exception:
                try:
                    await ch.send(f"⚠️ {target.mention} へDMを送信できませんでした。")
                except Exception:
                    pass


def setup(bot: commands.Bot):
    bot.add_cog(DMForward(bot))
