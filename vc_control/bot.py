from __future__ import annotations

import logging
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from vc_control.runtime import SessionManager
from vc_control.team_ui import TeamPanelView


class TeamCog(commands.Cog):
    def __init__(self, bot: "VoiceControlBot") -> None:
        self.bot = bot

    @app_commands.command(name="team", description="現在のVCセッションのチーム管理パネルを表示します。")
    async def team(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("サーバー内から実行してください。", ephemeral=True)
            return
        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("まず管理対象VCへ参加してください。", ephemeral=True)
            return
        session = self.bot.session_manager.get_session_by_channel(member.voice.channel.id)
        if session is None:
            await interaction.response.send_message("このVCは管理対象セッションではありません。", ephemeral=True)
            return
        await self.bot.session_manager.set_panel_creator(session.root_channel_id, member)
        embed = discord.Embed(
            title="チーム管理パネル",
            description=(
                f"メインVC: **{session.root_channel_name}**\n"
                f"開始ユーザー: <@{session.starter_user_id}>\n"
                f"現在の管理者: <@{session.owner_user_id}>\n"
                f"チーム: {', '.join(session.team_names)}"
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=TeamPanelView(self.bot.session_manager, session.root_channel_id),
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

    async def on_ready(self) -> None:
        if self.user is None:
            return
        self.logger.info("Discord Botとしてログインしました: %s", self.user)
        if self._bootstrapped:
            return
        self._bootstrapped = True
        await self.session_manager.sync_guild_catalog()
        await self.session_manager.restore_sessions()
        try:
            synced = await self.tree.sync()
            self.logger.info("スラッシュコマンドを同期しました: %s 件", len(synced))
        except discord.HTTPException:
            self.logger.exception("スラッシュコマンド同期に失敗しました")

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
        self.logger.info("サーバーへ参加しました: %s", guild.name)
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
