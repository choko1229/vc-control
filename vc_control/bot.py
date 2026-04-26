from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from vc_control.runtime import SessionManager
from vc_control.team_ui import TeamPanelView


def _read_sync_guild_ids() -> list[int]:
    raw = (os.getenv("DISCORD_SYNC_GUILD_ID") or os.getenv("GUILD_ID") or "").strip()
    if not raw:
        return []
    guild_ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            guild_ids.append(int(chunk))
        except ValueError:
            continue
    return guild_ids


class TeamCog(commands.Cog):
    def __init__(self, bot: "VoiceControlBot") -> None:
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name="team", description="チーム分けパネルを表示します。")
    async def team(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
            return
        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("VCに参加してから実行してください", ephemeral=True)
            return

        voice_session = self.bot.session_manager.get_session_by_channel(int(member.voice.channel.id))
        if voice_session is None:
            await interaction.response.send_message("このVCは管理対象セッションではありません。", ephemeral=True)
            return

        command_channel_id = int(interaction.channel_id or 0)
        command_session = self.bot.session_manager.get_session_by_channel(command_channel_id)
        if command_session is None or command_session.session_key != voice_session.session_key:
            await interaction.response.send_message("管理対象VCのテキスト欄で実行してください。", ephemeral=True)
            return

        await self.bot.session_manager.set_panel_creator(voice_session.root_channel_id, member)
        management_url = await self.bot.session_manager.build_management_url(
            voice_session.guild_id,
            voice_session.root_channel_id,
        )
        self.bot.logger.info(
            "Slash command /team 実行: guild=%s channel=%s user=%s session_key=%s",
            interaction.guild_id,
            command_channel_id,
            member.id,
            voice_session.session_key,
        )

        embed = discord.Embed(
            title="チーム管理パネル",
            description=(
                f"メインVC: **{voice_session.root_channel_name}**\n"
                f"開始ユーザー: <@{voice_session.starter_user_id}>\n"
                f"現在の管理者: <@{voice_session.owner_user_id}>\n"
                f"チーム: {', '.join(voice_session.team_names)}"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="VC管理", value=management_url or "未設定", inline=False)

        await interaction.response.send_message(
            embed=embed,
            view=TeamPanelView(
                self.bot.session_manager,
                voice_session.root_channel_id,
                management_url=management_url,
            ),
        )


class VoiceControlBot(commands.Bot):
    def __init__(self, session_manager: SessionManager, logger: logging.Logger) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        intents.messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.session_manager = session_manager
        self.logger = logger
        self.session_manager.bind_bot(self)
        self._bootstrapped = False

    async def setup_hook(self) -> None:
        await self.add_cog(TeamCog(self))
        self.logger.info("Cogを読み込みました: TeamCog")

    async def on_ready(self) -> None:
        if self.user is None:
            return
        self.logger.info("Discord Botとしてログインしました: %s", self.user)
        if self._bootstrapped:
            return
        self._bootstrapped = True

        await self.session_manager.sync_guild_catalog()
        await self.session_manager.restore_sessions()

        sync_guild_ids = _read_sync_guild_ids()
        try:
            if sync_guild_ids:
                for guild_id in sync_guild_ids:
                    guild = discord.Object(id=guild_id)
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    self.logger.info("Slash commandをギルド同期しました: guild_id=%s count=%s", guild_id, len(synced))
            else:
                if not self.guilds:
                    synced = await self.tree.sync()
                    self.logger.info("Slash commandをグローバル同期しました: count=%s", len(synced))
                for guild in self.guilds:
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    self.logger.info("Slash commandをギルド同期しました: guild_id=%s count=%s", guild.id, len(synced))
        except discord.HTTPException:
            self.logger.exception("Slash command の同期に失敗しました")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        try:
            await self.session_manager.handle_voice_state_update(member, before, after)
        except Exception:
            self.logger.exception("ボイス状態更新の処理中にエラーが発生しました")

    async def on_message(self, message: discord.Message) -> None:
        try:
            await self.session_manager.handle_message(message)
        except Exception:
            self.logger.exception("メッセージ処理中にエラーが発生しました")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.logger.info("サーバーに参加しました: %s", guild.name)
        await self.session_manager.sync_guild_catalog()

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self.logger.info("サーバーから退出しました: %s", guild.name)
        await self.session_manager.sync_guild_catalog()

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        try:
            await self.session_manager.handle_channel_delete(channel)
        except Exception:
            self.logger.exception("チャンネル削除イベント処理に失敗しました")


def build_bot(session_manager: SessionManager, logger: logging.Logger) -> VoiceControlBot:
    return VoiceControlBot(session_manager=session_manager, logger=logger)
