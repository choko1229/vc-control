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
        if not session.active_participants():
            await interaction.response.send_message("割り当て可能な参加者がいません。", ephemeral=True)
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
        super().__init__(placeholder="割り当てるユーザーを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.team_name = team_name

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
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
        super().__init__(placeholder="呼び戻すユーザーを選択", min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
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


class InviteUserSelect(discord.ui.UserSelect):
    def __init__(self, manager: SessionManager, root_channel_id: int) -> None:
        super().__init__(placeholder="招待するユーザーを選択", min_values=1, max_values=10)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        user_ids = [str(user.id) for user in self.values]
        try:
            await self.manager.add_invited_users(self.root_channel_id, member.id, user_ids)
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("招待ユーザーを更新しました。", ephemeral=True)


class InviteUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(InviteUserSelect(manager, root_channel_id))


class AccessRoleSelect(discord.ui.RoleSelect):
    def __init__(self, manager: SessionManager, root_channel_id: int) -> None:
        super().__init__(placeholder="許可するロールを選択", min_values=1, max_values=10)
        self.manager = manager
        self.root_channel_id = root_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        role_ids = [str(role.id) for role in self.values]
        try:
            await self.manager.update_access_control(
                self.root_channel_id,
                member.id,
                access_mode="role",
                access_role_ids=role_ids,
            )
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("ロールによるアクセス設定を更新しました。", ephemeral=True)


class AccessRoleView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(AccessRoleSelect(manager, root_channel_id))


class TeamPanelView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, management_url: str | None = None) -> None:
        super().__init__(timeout=None)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.management_url = management_url
        if management_url:
            self.add_item(discord.ui.Button(label="VCを管理", style=discord.ButtonStyle.link, url=management_url, row=0))

    @discord.ui.button(label="自分のチーム", style=discord.ButtonStyle.secondary, row=0)
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

    @discord.ui.button(label="他メンバー割当", style=discord.ButtonStyle.secondary, row=0)
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

    @discord.ui.button(label="チーム設定", style=discord.ButtonStyle.primary, row=0)
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

    @discord.ui.button(label="分割", style=discord.ButtonStyle.success, row=1)
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            result = await self.manager.split_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"分割を実行しました。対象チーム数: {len(result)}", ephemeral=True)

    @discord.ui.button(label="集合", style=discord.ButtonStyle.success, row=1)
    async def assemble(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            moved = await self.manager.assemble_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(f"集合を実行しました。対象 {len(moved)} 人。", ephemeral=True)

    @discord.ui.button(label="呼び戻し", style=discord.ButtonStyle.primary, row=1)
    async def recall(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return
        recallable = [
            participant
            for participant in session.active_participants()
            if participant.current_channel_id and participant.current_channel_id != session.root_channel_id
        ]
        if not recallable:
            await interaction.response.send_message("呼び戻せるユーザーがいません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "呼び戻すユーザーを選んでください。",
            ephemeral=True,
            view=RecallUserView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="Access: Public", style=discord.ButtonStyle.secondary, row=2)
    async def access_public(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        try:
            await self.manager.update_access_control(self.root_channel_id, member.id, access_mode="public")
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("VCのアクセスを公開に設定しました。", ephemeral=True)

    @discord.ui.button(label="Access: Invite", style=discord.ButtonStyle.secondary, row=2)
    async def access_invite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        try:
            await self.manager.update_access_control(self.root_channel_id, member.id, access_mode="invite")
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("招待するユーザーを選択してください。", ephemeral=True, view=InviteUserView(self.manager, self.root_channel_id))

    @discord.ui.button(label="Access: Roles", style=discord.ButtonStyle.secondary, row=2)
    async def access_roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("許可するロールを選択してください。", ephemeral=True, view=AccessRoleView(self.manager, self.root_channel_id))
