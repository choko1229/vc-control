from __future__ import annotations

import random
from typing import cast

import discord

from vc_control.runtime import LiveSession, SessionManager


FRUIT_NAMES = [
    "りんご",
    "みかん",
    "ぶどう",
    "もも",
    "なし",
    "すいか",
    "いちご",
    "メロン",
]


def _generate_team_names(mode: str, raw_names: str, current_count: int) -> list[str]:
    normalized_mode = mode.strip().lower()
    if normalized_mode in {"fruit", "fruits", "fruit_random"}:
        pool = FRUIT_NAMES.copy()
        random.shuffle(pool)
        count = max(1, current_count)
        return pool[:count]
    if normalized_mode in {"kansen", "kan", "㌠"}:
        count = max(1, current_count)
        labels = []
        for index in range(count):
            labels.append(f"{chr(ord('A') + index)}㌠")
        return labels
    names = [name.strip() for name in raw_names.split(",") if name.strip()]
    return names or ["A", "B", "C", "D"]


async def _post_history(channel: discord.abc.Messageable, title: str, description: str, color: discord.Color) -> None:
    await channel.send(embed=discord.Embed(title=title, description=description, color=color))


class TeamSettingsModal(discord.ui.Modal, title="チーム設定の編集"):
    mode_input = discord.ui.TextInput(
        label="モード (custom / fruit / kansen)",
        default="custom",
        max_length=20,
        required=True,
    )
    names_input = discord.ui.TextInput(
        label="チーム名 (custom時のみ, カンマ区切り)",
        default="A,B,C,D",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200,
    )

    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__()
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.mode_input.default = session.team_mode
        self.names_input.default = ",".join(session.team_names)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        try:
            mode_value = self.mode_input.value.strip()
            names_value = self.names_input.value.strip()
            names = _generate_team_names(mode_value, names_value, len(session.team_names))
            await self.manager.update_team_settings(
                self.root_channel_id,
                member.id,
                names,
                mode_value,
            )
        except PermissionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("チーム設定を更新しました。", ephemeral=True)
        if interaction.channel:
            await _post_history(
                interaction.channel,
                "チーム設定更新",
                f"モード: `{mode_value}`\nチーム名: {', '.join(names)}",
                discord.Color.blue(),
            )


class SelfTeamSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        options = [discord.SelectOption(label="未所属", value="__none__")]
        for name in session.team_names:
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="自分のチームを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        selected = None if self.values[0] == "__none__" else self.values[0]
        try:
            message = await self.manager.assign_team(self.root_channel_id, member.id, member.id, selected)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("自分のチームを更新しました。", ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, "チーム割り当て", message, discord.Color.green())


class SelfTeamView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(SelfTeamSelect(manager, root_channel_id, session))


class AssignTeamSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        options = [discord.SelectOption(label="未所属", value="__none__")]
        for name in session.team_names:
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="まずチームを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message("他ユーザーの割り当て権限がありません。", ephemeral=True)
            return
        selected = None if self.values[0] == "__none__" else self.values[0]
        await interaction.response.send_message(
            "次に割り当て対象のユーザーを選んでください。",
            ephemeral=True,
            view=AssignUserView(self.manager, self.root_channel_id, session, selected),
        )


class AssignTeamView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(AssignTeamSelect(manager, root_channel_id, session))


class AssignUserSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession, team_name: str | None) -> None:
        options = [
            discord.SelectOption(label=participant.user_name, value=str(participant.user_id))
            for participant in session.active_participants()
        ]
        if not options:
            options = [discord.SelectOption(label="対象なし", value="0", default=True)]
        super().__init__(placeholder="割り当てるユーザーを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.team_name = team_name

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        if self.values[0] == "0":
            await interaction.response.send_message("割り当て可能な参加者がいません。", ephemeral=True)
            return
        try:
            message = await self.manager.assign_team(self.root_channel_id, member.id, int(self.values[0]), self.team_name)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("チーム割り当てを更新しました。", ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, "チーム割り当て", message, discord.Color.green())


class AssignUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession, team_name: str | None) -> None:
        super().__init__(timeout=180)
        self.add_item(AssignUserSelect(manager, root_channel_id, session, team_name))


class RecallUserSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        root_channel_id_value = session.root_channel_id
        options: list[discord.SelectOption] = []
        for participant in session.active_participants():
            if participant.current_channel_id and participant.current_channel_id != root_channel_id_value:
                options.append(discord.SelectOption(label=participant.user_name, value=str(participant.user_id)))
        if not options:
            options = [discord.SelectOption(label="対象なし", value="0", default=True)]
        super().__init__(placeholder="呼び戻すユーザーを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        if self.values[0] == "0":
            await interaction.response.send_message("呼び戻せるユーザーがいません。", ephemeral=True)
            return
        try:
            message = await self.manager.recall_member(self.root_channel_id, member.id, int(self.values[0]))
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("呼び戻しを実行しました。", ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, "呼び戻し", message, discord.Color.gold())


class RecallUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(RecallUserSelect(manager, root_channel_id, session))


class MainSessionControlView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, management_url: str | None = None) -> None:
        super().__init__(timeout=None)
        self.manager = manager
        self.root_channel_id = root_channel_id
        if management_url:
            self.add_item(discord.ui.Button(label="VCを管理", style=discord.ButtonStyle.link, url=management_url))

    @discord.ui.button(label="集合", style=discord.ButtonStyle.success)
    async def collect(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            moved = await self.manager.assemble_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"集合を実行しました。対象 {len(moved)} 人。", ephemeral=True)

    @discord.ui.button(label="呼び戻し", style=discord.ButtonStyle.primary)
    async def recall(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "呼び戻すユーザーを選択してください。",
            ephemeral=True,
            view=RecallUserView(self.manager, self.root_channel_id, session),
        )


class TeamPanelView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, management_url: str | None = None) -> None:
        super().__init__(timeout=None)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.management_url = management_url
        if management_url:
            self.add_item(discord.ui.Button(label="VCを管理", style=discord.ButtonStyle.link, url=management_url))

    @discord.ui.button(label="自分のチーム", style=discord.ButtonStyle.secondary)
    async def my_team(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "所属したいチームを選択してください。",
            ephemeral=True,
            view=SelfTeamView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="他メンバー割当", style=discord.ButtonStyle.secondary)
    async def assign_other(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message("他ユーザーの割り当て権限がありません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "割り当て先チームを選択してください。",
            ephemeral=True,
            view=AssignTeamView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="チーム設定", style=discord.ButtonStyle.primary)
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message("チーム設定の変更権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(TeamSettingsModal(self.manager, self.root_channel_id, session))

    @discord.ui.button(label="分割", style=discord.ButtonStyle.success)
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            result = await self.manager.split_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"分割を実行しました。対象チーム数: {len(result)}", ephemeral=True)
        target_channel = self.manager.resolve_voice_channel(self.root_channel_id) or interaction.channel
        session = self.manager.get_session_by_root(self.root_channel_id)
        management_url = None
        if session is not None:
            management_url = await self.manager.build_management_url(session.guild_id, session.root_channel_id)
        if target_channel and result:
            description = "\n".join(result)
            if management_url:
                description = f"{description}\n\nVC管理: {management_url}"
            await target_channel.send(
                embed=discord.Embed(
                    title="チーム分割操作",
                    description=description,
                    color=discord.Color.blue(),
                ),
                view=MainSessionControlView(self.manager, self.root_channel_id, management_url=management_url),
            )

    @discord.ui.button(label="集合", style=discord.ButtonStyle.success)
    async def assemble(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            moved = await self.manager.assemble_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"集合を実行しました。対象 {len(moved)} 人。", ephemeral=True)

    @discord.ui.button(label="呼び戻し", style=discord.ButtonStyle.primary)
    async def recall(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "呼び戻すユーザーを選んでください。",
            ephemeral=True,
            view=RecallUserView(self.manager, self.root_channel_id, session),
        )
