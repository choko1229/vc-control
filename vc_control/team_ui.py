from __future__ import annotations

import random
from typing import cast

import discord

from vc_control.embeds import COLOR_NOTIFY, COLOR_SUCCESS, build_embed
from vc_control.i18n import t
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


def _locale_for(manager: SessionManager, guild_id: int) -> str | None:
    config = manager.guild_configs.get(guild_id)
    return config.guild_language if config else None


async def _post_history(channel: discord.abc.Messageable, locale: str | None, title_key: str, description: str, color: discord.Color) -> None:
    embed = build_embed(locale, title_key, color=color)
    embed.description = description
    await channel.send(embed=embed)


class TeamSettingsModal(discord.ui.Modal):
    mode_input = discord.ui.TextInput(
        default="custom",
        max_length=20,
        required=True,
    )
    names_input = discord.ui.TextInput(
        default="A,B,C,D",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200,
    )

    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        locale = _locale_for(manager, session.guild_id)
        super().__init__(title=t("team.modal.settingsTitle", locale))
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale
        self.mode_input.label = t("team.modal.modeLabel", locale)
        self.names_input.label = t("team.modal.namesLabel", locale)
        self.mode_input.default = session.team_mode
        self.names_input.default = ",".join(session.team_names)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", self.locale), ephemeral=True)
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
        await interaction.response.send_message(t("team.msg.settingsUpdated", self.locale), ephemeral=True)
        if interaction.channel:
            await _post_history(
                interaction.channel,
                self.locale,
                "team.history.settingsUpdatedTitle",
                t("team.history.settingsUpdatedDesc", self.locale, mode=mode_value, names=", ".join(names)),
                COLOR_NOTIFY,
            )


class SelfTeamSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        locale = _locale_for(manager, session.guild_id)
        options = [discord.SelectOption(label=t("common.unassigned", locale), value="__none__")]
        for name in session.team_names:
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder=t("team.select.myTeamPlaceholder", locale), min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        selected = None if self.values[0] == "__none__" else self.values[0]
        try:
            message = await self.manager.assign_team(self.root_channel_id, member.id, member.id, selected)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(t("team.msg.myTeamUpdated", self.locale), ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, self.locale, "team.history.teamAssignedTitle", message, COLOR_SUCCESS)


class SelfTeamView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(SelfTeamSelect(manager, root_channel_id, session))


class AssignTeamSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        locale = _locale_for(manager, session.guild_id)
        options = [discord.SelectOption(label=t("common.unassigned", locale), value="__none__")]
        for name in session.team_names:
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder=t("team.select.assignTeamPlaceholder", locale), min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", self.locale), ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message(t("team.msg.noPermissionAssignOthers", self.locale), ephemeral=True)
            return
        if not session.active_participants():
            await interaction.response.send_message(t("team.msg.noAssignableParticipants", self.locale), ephemeral=True)
            return
        selected = None if self.values[0] == "__none__" else self.values[0]
        await interaction.response.send_message(
            t("team.msg.selectAssignTarget", self.locale),
            ephemeral=True,
            view=AssignUserView(self.manager, self.root_channel_id, session, selected),
        )

class AssignTeamView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(AssignTeamSelect(manager, root_channel_id, session))


class AssignUserSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession, team_name: str | None) -> None:
        locale = _locale_for(manager, session.guild_id)
        options = [
            discord.SelectOption(label=participant.user_name, value=str(participant.user_id))
            for participant in session.active_participants()
        ]
        super().__init__(placeholder=t("team.select.assignUserPlaceholder", locale), min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.team_name = team_name
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            message = await self.manager.assign_team(self.root_channel_id, member.id, int(self.values[0]), self.team_name)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(t("team.msg.teamAssignmentUpdated", self.locale), ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, self.locale, "team.history.teamAssignedTitle", message, COLOR_SUCCESS)


class AssignUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession, team_name: str | None) -> None:
        super().__init__(timeout=180)
        self.add_item(AssignUserSelect(manager, root_channel_id, session, team_name))


class RecallUserSelect(discord.ui.Select):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        locale = _locale_for(manager, session.guild_id)
        root_channel_id_value = session.root_channel_id
        options: list[discord.SelectOption] = []
        for participant in session.active_participants():
            if participant.current_channel_id and participant.current_channel_id != root_channel_id_value:
                options.append(discord.SelectOption(label=participant.user_name, value=str(participant.user_id)))
        super().__init__(placeholder=t("team.select.recallUserPlaceholder", locale), min_values=1, max_values=1, options=options)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        member = cast(discord.Member, interaction.user)
        try:
            message = await self.manager.recall_member(self.root_channel_id, member.id, int(self.values[0]))
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(t("team.msg.recallExecuted", self.locale), ephemeral=True)
        if interaction.channel:
            await _post_history(interaction.channel, self.locale, "team.history.recallTitle", message, COLOR_NOTIFY)


class RecallUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, session: LiveSession) -> None:
        super().__init__(timeout=180)
        self.add_item(RecallUserSelect(manager, root_channel_id, session))


class InviteUserSelect(discord.ui.UserSelect):
    def __init__(self, manager: SessionManager, root_channel_id: int, locale: str | None = None) -> None:
        super().__init__(placeholder=t("team.select.inviteUserPlaceholder", locale), min_values=1, max_values=10)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        user_ids = [str(user.id) for user in self.values]
        try:
            await self.manager.add_invited_users(self.root_channel_id, member.id, user_ids)
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(t("team.msg.inviteUpdated", self.locale), ephemeral=True)


class InviteUserView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, locale: str | None = None) -> None:
        super().__init__(timeout=180)
        self.add_item(InviteUserSelect(manager, root_channel_id, locale))


class AccessRoleSelect(discord.ui.RoleSelect):
    def __init__(self, manager: SessionManager, root_channel_id: int, locale: str | None = None) -> None:
        super().__init__(placeholder=t("team.select.accessRolePlaceholder", locale), min_values=1, max_values=10)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.locale = locale

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
        await interaction.followup.send(t("team.msg.roleAccessUpdated", self.locale), ephemeral=True)


class AccessRoleView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, locale: str | None = None) -> None:
        super().__init__(timeout=180)
        self.add_item(AccessRoleSelect(manager, root_channel_id, locale))


class TeamPanelView(discord.ui.View):
    def __init__(self, manager: SessionManager, root_channel_id: int, management_url: str | None = None) -> None:
        super().__init__(timeout=None)
        self.manager = manager
        self.root_channel_id = root_channel_id
        self.management_url = management_url
        session = manager.get_session_by_root(root_channel_id)
        locale = _locale_for(manager, session.guild_id) if session is not None else None
        self.my_team.label = t("team.button.myTeam", locale)
        self.assign_other.label = t("team.button.assignOther", locale)
        self.settings.label = t("team.button.settings", locale)
        self.split.label = t("team.button.split", locale)
        self.assemble.label = t("team.button.assemble", locale)
        self.recall.label = t("team.button.recall", locale)
        self.access_public.label = t("team.button.accessPublic", locale)
        self.access_invite.label = t("team.button.accessInvite", locale)
        self.access_roles.label = t("team.button.accessRoles", locale)
        if management_url:
            self.add_item(discord.ui.Button(label=t("team.button.manageVc", locale), style=discord.ButtonStyle.link, url=management_url, row=0))

    @discord.ui.button(label="自分のチーム", style=discord.ButtonStyle.secondary, row=0)
    async def my_team(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", locale), ephemeral=True)
            return
        await interaction.response.send_message(
            t("team.msg.selectMyTeam", locale),
            ephemeral=True,
            view=SelfTeamView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="他メンバー割当", style=discord.ButtonStyle.secondary, row=0)
    async def assign_other(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", locale), ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message(t("team.msg.noPermissionAssignOthers", locale), ephemeral=True)
            return
        await interaction.response.send_message(
            t("team.msg.selectAssignTeam", locale),
            ephemeral=True,
            view=AssignTeamView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="チーム設定", style=discord.ButtonStyle.primary, row=0)
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", locale), ephemeral=True)
            return
        if not await self.manager.can_assign_others(session, member.id):
            await interaction.response.send_message(t("msg.noPermissionTeamSettings", locale), ephemeral=True)
            return
        await interaction.response.send_modal(TeamSettingsModal(self.manager, self.root_channel_id, session))

    @discord.ui.button(label="分割", style=discord.ButtonStyle.success, row=1)
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        try:
            result = await self.manager.split_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(t("team.msg.splitExecuted", locale, count=len(result)), ephemeral=True)

    @discord.ui.button(label="集合", style=discord.ButtonStyle.success, row=1)
    async def assemble(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        try:
            moved = await self.manager.assemble_teams(self.root_channel_id, member.id)
        except (PermissionError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(t("team.msg.assembleExecuted", locale, count=len(moved)), ephemeral=True)

    @discord.ui.button(label="呼び戻し", style=discord.ButtonStyle.primary, row=1)
    async def recall(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        if session is None:
            await interaction.response.send_message(t("msg.sessionNotFound", locale), ephemeral=True)
            return
        recallable = [
            participant
            for participant in session.active_participants()
            if participant.current_channel_id and participant.current_channel_id != session.root_channel_id
        ]
        if not recallable:
            await interaction.response.send_message(t("team.msg.noRecallableUsers", locale), ephemeral=True)
            return
        await interaction.response.send_message(
            t("team.msg.selectRecallTarget", locale),
            ephemeral=True,
            view=RecallUserView(self.manager, self.root_channel_id, session),
        )

    @discord.ui.button(label="Access: Public", style=discord.ButtonStyle.secondary, row=2)
    async def access_public(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        try:
            await self.manager.update_access_control(self.root_channel_id, member.id, access_mode="public")
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(t("team.msg.accessSetPublic", locale), ephemeral=True)

    @discord.ui.button(label="Access: Invite", style=discord.ButtonStyle.secondary, row=2)
    async def access_invite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        member = cast(discord.Member, interaction.user)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        try:
            await self.manager.update_access_control(self.root_channel_id, member.id, access_mode="invite")
        except (PermissionError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            t("team.msg.selectInviteUsers", locale), ephemeral=True, view=InviteUserView(self.manager, self.root_channel_id, locale)
        )

    @discord.ui.button(label="Access: Roles", style=discord.ButtonStyle.secondary, row=2)
    async def access_roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        session = self.manager.get_session_by_root(self.root_channel_id)
        locale = _locale_for(self.manager, session.guild_id) if session is not None else None
        await interaction.followup.send(
            t("team.msg.selectAllowedRoles", locale), ephemeral=True, view=AccessRoleView(self.manager, self.root_channel_id, locale)
        )
