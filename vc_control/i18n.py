from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "ja"
SUPPORTED_LOCALES = ("ja", "en")

TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- Shared field labels (reused across embeds) ---
    "field.vcName": {"ja": "VC名", "en": "VC name"},
    "field.startedAt": {"ja": "開始時刻", "en": "Started at"},
    "field.participant": {"ja": "参加者", "en": "Participant"},
    "field.management": {"ja": "VC管理", "en": "Manage VC"},
    "field.currentOwner": {"ja": "現在の管理者", "en": "Current owner"},
    "field.teams": {"ja": "チーム", "en": "Teams"},
    "field.vc": {"ja": "VC", "en": "VC"},
    "field.startedShort": {"ja": "開始", "en": "Started"},
    "field.endedShort": {"ja": "終了", "en": "Ended"},
    "field.duration": {"ja": "時間", "en": "Duration"},
    "field.participantList": {"ja": "参加ユーザー一覧", "en": "Participants"},
    "field.totalTalkTime": {"ja": "VC全体の利用時間", "en": "Total talk time"},
    "field.owner": {"ja": "所有者", "en": "Owner"},
    "field.scheduledEnd": {"ja": "終了予定", "en": "Scheduled end"},
    "field.description": {"ja": "説明", "en": "Description"},
    "field.mainVc": {"ja": "メインVC", "en": "Main VC"},
    "field.starter": {"ja": "開始ユーザー", "en": "Started by"},
    "common.notSet": {"ja": "未設定", "en": "Not set"},
    "common.noParticipants": {"ja": "参加者なし", "en": "No participants"},
    "common.unknown": {"ja": "不明", "en": "Unknown"},
    "common.noData": {"ja": "データがありません", "en": "No data"},
    "common.unassigned": {"ja": "未所属", "en": "Unassigned"},

    # --- Timeline event labels (TIMELINE_EVENT_LABELS) ---
    "timeline.vc_started": {"ja": "VC開始", "en": "VC started"},
    "timeline.vc_ended": {"ja": "VC終了", "en": "VC ended"},
    "timeline.member_joined": {"ja": "参加", "en": "Joined"},
    "timeline.member_left": {"ja": "退出", "en": "Left"},
    "timeline.member_moved": {"ja": "移動", "en": "Moved"},
    "timeline.member_mute_changed": {"ja": "ミュート変更", "en": "Mute changed"},
    "timeline.teams_split": {"ja": "チーム分割", "en": "Teams split"},
    "timeline.teams_assembled": {"ja": "集合", "en": "Teams assembled"},
    "timeline.member_recalled": {"ja": "呼び戻し", "en": "Recalled"},
    "timeline.voice_settings_changed": {"ja": "VC名変更", "en": "VC settings changed"},
    "timeline.team_changed": {"ja": "チーム変更", "en": "Team changed"},
    "timeline.bot_restart_restored": {"ja": "BOT再起動復元", "en": "Restored after bot restart"},
    "timeline.scheduled_vc_created": {"ja": "予約VC作成", "en": "Scheduled VC created"},
    "timeline.web_vc_created": {"ja": "Web VC作成", "en": "Web VC created"},
    "timeline.access_changed": {"ja": "アクセス変更", "en": "Access changed"},

    # --- Access mode labels (ACCESS_MODE_LABELS) ---
    "access.mode.public": {"ja": "公開", "en": "Public"},
    "access.mode.invite": {"ja": "招待制", "en": "Invite only"},
    "access.mode.role": {"ja": "ロール制限", "en": "Role restricted"},

    # --- Ranking target labels (RANKING_TARGET_LABELS) ---
    "ranking.target.top_talkers": {"ja": "今日最も通話した人", "en": "Today's top talkers"},
    "ranking.target.top_hosts": {"ja": "最も人を集めたVC主", "en": "Most popular VC host"},
    "ranking.target.team_splits": {"ja": "チーム分け回数", "en": "Team split count"},
    "ranking.target.night_owls": {"ja": "深夜勢ランキング", "en": "Night owl ranking"},
    "ranking.freq.manual": {"ja": "手動投稿", "en": "Manual post"},
    "ranking.freq.daily": {"ja": "毎日", "en": "Daily"},
    "ranking.freq.weekly": {"ja": "毎週", "en": "Weekly"},
    "ranking.freq.monthly": {"ja": "毎月", "en": "Monthly"},
    "ranking.hostValue": {"ja": "{gathered}人 / {sessions}VC", "en": "{gathered} people / {sessions} VCs"},
    "ranking.splitValue": {"ja": "{count}回", "en": "{count} times"},
    "ranking.footer": {"ja": "深夜勢: 0時〜5時", "en": "Night owls: 0:00-5:00"},

    # --- Embeds: VC lifecycle ---
    "embed.vc_started.title": {"ja": "VC開始", "en": "VC started"},
    "embed.vc_started.description": {"ja": "**{channel}** のセッションを開始しました。", "en": "Started a session in **{channel}**."},
    "embed.management_panel.title": {"ja": "VC管理パネル", "en": "VC management panel"},
    "embed.management_panel.description": {
        "ja": "チーム操作はこのメッセージか `/team` から実行できます。",
        "en": "Use this message or `/team` to manage teams.",
    },
    "embed.management_panel_restored.title": {"ja": "VC管理パネル(復元)", "en": "VC management panel (restored)"},
    "embed.management_panel_restored.description": {
        "ja": "このVCセッションはBot再起動後に復元されました。\n古い管理パネルのボタンが反応しない場合は、この新しいパネルを使用してください。",
        "en": "This VC session was restored after a bot restart.\nIf the old panel's buttons don't respond, use this new panel instead.",
    },
    "embed.vc_ended.title": {"ja": "VC終了", "en": "VC ended"},
    "embed.vc_ended.description": {"ja": "**{channel}** のセッションを終了しました。", "en": "Ended the session in **{channel}**."},
    "embed.web_vc_created.title": {"ja": "Web VCが作成されました", "en": "VC created from the web dashboard"},
    "embed.web_vc_created.description": {
        "ja": "**{channel}** がWebダッシュボードから作成されました。",
        "en": "**{channel}** was created from the web dashboard.",
    },

    # --- Embeds: scheduled VC ---
    "embed.scheduled_vc_started.title": {"ja": "予約VCを開始しました: {name}", "en": "Started scheduled VC: {name}"},
    "scheduled.defaultDescription": {"ja": "予約VCの準備ができました。", "en": "The scheduled VC is ready."},
    "scheduled.endAtSuffix": {"ja": "\n終了予定: {time}", "en": "\nScheduled end: {time}"},
    "embed.scheduled_vc_ending.title": {"ja": "予約VCは{minutes}分後に終了します", "en": "Scheduled VC ends in {minutes} min"},
    "embed.scheduled_vc_ending.description": {"ja": "**{name}** はまもなく終了します。", "en": "**{name}** will end soon."},

    # --- Embeds: join / leave / move notices ---
    "embed.member_joined.title": {"ja": "入室通知", "en": "Join notice"},
    "embed.member_joined.description": {"ja": "{mention} が通話に参加しました。", "en": "{mention} joined the call."},
    "embed.member_left.title": {"ja": "退出通知", "en": "Leave notice"},
    "embed.member_left.description": {"ja": "{mention} が通話から退出しました。", "en": "{mention} left the call."},
    "embed.owner_changed.title": {"ja": "セッション管理者変更", "en": "Session owner changed"},
    "embed.owner_changed.description": {
        "ja": "現在の管理者が退出したため、管理者を {mention} に移譲しました。",
        "en": "The previous owner left, so ownership was transferred to {mention}.",
    },
    "embed.member_moved_leave.title": {"ja": "移動通知", "en": "Move notice"},
    "embed.member_moved_leave.description": {
        "ja": "{mention} が **{channel}** から移動しました。",
        "en": "{mention} moved out of **{channel}**.",
    },
    "embed.member_moved_join.title": {"ja": "移動通知", "en": "Move notice"},
    "embed.member_moved_join.description": {
        "ja": "{mention} が **{channel}** に参加しました。",
        "en": "{mention} moved into **{channel}**.",
    },

    # --- Embeds: warnings / mentions ---
    "embed.everyone_mention_warning.title": {"ja": "警告", "en": "Warning"},
    "embed.everyone_mention_warning.description": {
        "ja": "@everyone / @here のDM転送は行いません。",
        "en": "@everyone/@here mentions are not forwarded via DM.",
    },
    "embed.vc_mention.title": {"ja": "VCメンション通知", "en": "VC mention notice"},
    "embed.vc_mention.description": {
        "ja": "{author} さんから {channel} でメンションされました。\n\n{content}",
        "en": "{author} mentioned you in {channel}.\n\n{content}",
    },

    # --- Embeds: teams ---
    "embed.team_moved.title": {"ja": "チーム移動", "en": "Team move"},
    "embed.team_moved.description": {"ja": "{names} を **{team}** へ移動しました。", "en": "Moved {names} to **{team}**."},
    "embed.teams_split.title": {"ja": "チーム分割完了", "en": "Teams split"},
    "embed.teams_assembled.title": {"ja": "集合完了", "en": "Teams assembled"},
    "embed.teams_assembled.description": {
        "ja": "{names} をメインVCへ戻しました。",
        "en": "Moved {names} back to the main VC.",
    },
    "embed.member_recalled.title": {"ja": "呼び戻し", "en": "Recalled"},

    # --- Embeds: solo VC cleanup / empty-room cleanup ---
    "embed.solo_warning.title": {"ja": "ソロVC削除警告", "en": "Solo VC deletion warning"},
    "embed.solo_notice.title": {"ja": "ソロVCへの招待提案", "en": "Consider inviting others"},
    "embed.solo_notice.description": {
        "ja": "{mention} さんがしばらく **{channel}** に1人でいます。\n他のユーザーをメンションして招待することを検討してください。",
        "en": "{mention} has been alone in **{channel}** for a while.\nConsider mentioning and inviting others.",
    },
    "embed.solo_warning.suffix": {
        "ja": "\nこのままソロの状態が続くと、このVCは自動的に削除されます。",
        "en": "\nIf this continues, this VC will be deleted automatically.",
    },
    "embed.delete_notice.title": {"ja": "削除予告", "en": "Deletion notice"},
    "embed.delete_notice.description": {
        "ja": "{seconds}秒後まで空室ならVCを削除します。",
        "en": "This VC will be deleted if it's still empty in {seconds} seconds.",
    },
    "embed.delete_cancelled.title": {"ja": "削除キャンセル", "en": "Deletion cancelled"},
    "embed.delete_cancelled.description": {
        "ja": "再入室を検知したため、自動削除をキャンセルしました。",
        "en": "Cancelled automatic deletion because someone rejoined.",
    },

    # --- Embeds: ranking post ---
    "embed.ranking.title": {"ja": "アクティビティランキング - {suffix}", "en": "Activity Ranking - {suffix}"},
    "embed.ranking.description": {"ja": "{guild} の活動サマリーです。", "en": "Activity summary for {guild}."},

    # --- Embeds: /team panel (bot.py) ---
    "embed.team_panel.title": {"ja": "チーム管理パネル", "en": "Team management panel"},
    "embed.team_panel.description": {
        "ja": "メインVC: **{channel}**\n開始ユーザー: {starter}\n現在の管理者: {owner}\nチーム: {teams}",
        "en": "Main VC: **{channel}**\nStarted by: {starter}\nCurrent owner: {owner}\nTeams: {teams}",
    },

    # --- Important-event / notification-center titles & messages ---
    "event.restoredAfterRestart": {"ja": "{channel} はBot再起動後に復元されました。", "en": "{channel} was restored after a bot restart."},
    "event.restoredFromDiscordState": {
        "ja": "{channel} は現在のDiscord状態から復元されました。",
        "en": "{channel} was restored from the current Discord state.",
    },
    "event.title.restored": {"ja": "Bot再起動から復元", "en": "Restored after bot restart"},
    "event.title.vcStarted": {"ja": "VC開始", "en": "VC started"},
    "event.vcStartedDesc": {"ja": "{channel} が開始されました。", "en": "{channel} started."},
    "event.title.vcEnded": {"ja": "VC終了", "en": "VC ended"},
    "event.vcEndedDesc": {"ja": "{channel} が終了しました。", "en": "{channel} ended."},
    "event.title.accessChanged": {"ja": "VCアクセスが変更されました", "en": "VC access changed"},
    "event.accessChangedDesc": {
        "ja": "{channel} のアクセスモードが{mode}に変更されました。",
        "en": "{channel}'s access mode was changed to {mode}.",
    },
    "event.webVcCreatedByActor": {"ja": "{channel} が {actor} によって作成されました。", "en": "{channel} was created by {actor}."},

    # --- Scheduled VC errors / notifications ---
    "scheduled.error.createTitle": {"ja": "予約VCの作成エラー", "en": "Scheduled VC creation error"},
    "scheduled.error.guildNotFound": {"ja": "サーバーが見つかりません。", "en": "The server could not be found."},
    "scheduled.error.categoryUnavailable": {"ja": "設定されたカテゴリが利用できません。", "en": "The configured category is unavailable."},
    "scheduled.error.permissionTitle": {"ja": "予約VCの権限がありません", "en": "Missing permission for scheduled VC"},
    "scheduled.error.createPermission": {"ja": "Botに予約VCを作成する権限がありません。", "en": "The bot lacks permission to create the scheduled VC."},
    "scheduled.error.createFailed": {"ja": "予約VCの作成に失敗しました。", "en": "Failed to create the scheduled VC."},
    "scheduled.notif.startedTitle": {"ja": "予約VCを開始しました", "en": "Scheduled VC started"},
    "scheduled.notif.startedDesc": {"ja": "{name} を作成しました。", "en": "Created {name}."},
    "scheduled.notif.endedTitle": {"ja": "予約VCが終了しました", "en": "Scheduled VC ended"},
    "scheduled.notif.endedDesc": {"ja": "{name} が終了しました。", "en": "{name} ended."},
    "scheduled.error.deleteTitle": {"ja": "予約VCの削除エラー", "en": "Scheduled VC deletion error"},
    "scheduled.error.deleteFailed": {"ja": "予約VCの削除に失敗しました。", "en": "Failed to delete the scheduled VC."},
    "scheduled.error.deletePermissionTitle": {"ja": "予約VCの削除権限がありません", "en": "Missing permission to delete scheduled VC"},
    "scheduled.error.deletePermission": {
        "ja": "Botに予約VCチャンネルを削除する権限がありません。",
        "en": "The bot lacks permission to delete the scheduled VC channel.",
    },

    # --- SessionManager return-value / exception messages (surfaced via Discord ephemeral replies) ---
    "msg.sessionNotFound": {"ja": "セッションが見つかりません。", "en": "The session could not be found."},
    "msg.targetUserNotFound": {"ja": "対象ユーザーが見つかりません。", "en": "The target user could not be found."},
    "msg.noPermissionAssignOthers": {"ja": "他ユーザーのチーム変更権限がありません。", "en": "You don't have permission to change other users' teams."},
    "msg.teamNotExist": {"ja": "存在しないチームです。", "en": "That team does not exist."},
    "msg.teamAssignedTo": {"ja": "<@{userId}> を {team} に設定しました。", "en": "Set <@{userId}> to {team}."},
    "msg.noPermissionTeamSettings": {"ja": "チーム設定の変更権限がありません。", "en": "You don't have permission to change team settings."},
    "msg.teamNamesRequired": {"ja": "少なくとも1つのチーム名が必要です。", "en": "At least one team name is required."},
    "msg.noPermissionSplit": {"ja": "分割権限がありません。", "en": "You don't have permission to split teams."},
    "msg.channelUnresolvable": {"ja": "Discord上のチャンネルを解決できません。", "en": "Could not resolve the Discord channel."},
    "msg.noPermissionAssemble": {"ja": "集合権限がありません。", "en": "You don't have permission to assemble teams."},
    "msg.noPermissionRecall": {"ja": "呼び戻し権限がありません。", "en": "You don't have permission to recall members."},
    "msg.targetNotInVoice": {"ja": "対象ユーザーが現在通話にいません。", "en": "The target user is not currently in a call."},
    "msg.recallFailed": {"ja": "呼び戻しに失敗しました。", "en": "Failed to recall the member."},
    "msg.recalledTo": {"ja": "<@{userId}> をメインVCへ呼び戻しました。", "en": "Recalled <@{userId}> to the main VC."},
    "msg.channelNotFound": {"ja": "チャンネルが見つかりません。", "en": "The channel could not be found."},
    "msg.guildNotFound": {"ja": "ギルドが見つかりません。", "en": "The server could not be found."},
    "msg.noPermissionAccessControl": {"ja": "アクセス制御の変更権限がありません。", "en": "You don't have permission to change access control."},
    "msg.accessModeUpdated": {"ja": "アクセスモードを{mode}に更新しました。", "en": "Updated the access mode to {mode}."},
    "msg.noPermissionChannelUpdate": {"ja": "Botにチャンネル権限を更新する権限がありません。", "en": "The bot lacks permission to update channel permissions."},
    "msg.channelPermissionUpdateFailed": {"ja": "チャンネル権限の更新に失敗しました。", "en": "Failed to update channel permissions."},
    "msg.adminPermissionRequired": {"ja": "サーバー管理者権限が必要です。", "en": "Server administrator permission is required."},
    "msg.noManagedCategory": {"ja": "管理対象カテゴリが設定されていません。", "en": "No managed category is configured."},
    "msg.managedCategoryUnavailable": {"ja": "管理対象カテゴリが利用できません。", "en": "The managed category is unavailable."},
    "msg.ownerRequired": {"ja": "所有者ユーザーの指定が必要です。", "en": "An owner user must be specified."},
    "msg.endAtRequired": {"ja": "一時イベントVCには終了時刻の指定が必要です。", "en": "An end time is required for a temporary event VC."},
    "msg.noPermissionCreateChannel": {"ja": "Botにボイスチャンネルを作成する権限がありません。", "en": "The bot lacks permission to create a voice channel."},
    "msg.createChannelFailed": {"ja": "ボイスチャンネルの作成に失敗しました。", "en": "Failed to create the voice channel."},
    "msg.personalVcName": {"ja": "{name}のVC", "en": "{name}'s VC"},
    "msg.eventVcDefaultName": {"ja": "一時イベントVC", "en": "Temporary event VC"},

    # --- team_ui.py: modal / select / button labels ---
    "team.modal.settingsTitle": {"ja": "チーム設定の編集", "en": "Edit team settings"},
    "team.modal.modeLabel": {"ja": "モード (custom / fruit / kansen)", "en": "Mode (custom / fruit / kansen)"},
    "team.modal.namesLabel": {"ja": "チーム名 (custom時のみ, カンマ区切り)", "en": "Team names (custom mode only, comma-separated)"},
    "team.select.myTeamPlaceholder": {"ja": "自分のチームを選択", "en": "Select your team"},
    "team.select.assignTeamPlaceholder": {"ja": "まずチームを選択", "en": "Select a team first"},
    "team.select.assignUserPlaceholder": {"ja": "割り当てるユーザーを選択", "en": "Select a user to assign"},
    "team.select.recallUserPlaceholder": {"ja": "呼び戻すユーザーを選択", "en": "Select a user to recall"},
    "team.select.inviteUserPlaceholder": {"ja": "招待するユーザーを選択", "en": "Select users to invite"},
    "team.select.accessRolePlaceholder": {"ja": "許可するロールを選択", "en": "Select allowed roles"},
    "team.button.myTeam": {"ja": "自分のチーム", "en": "My team"},
    "team.button.assignOther": {"ja": "他メンバー割当", "en": "Assign member"},
    "team.button.settings": {"ja": "チーム設定", "en": "Team settings"},
    "team.button.split": {"ja": "分割", "en": "Split"},
    "team.button.assemble": {"ja": "集合", "en": "Assemble"},
    "team.button.recall": {"ja": "呼び戻し", "en": "Recall"},
    "team.button.accessPublic": {"ja": "Access: Public", "en": "Access: Public"},
    "team.button.accessInvite": {"ja": "Access: Invite", "en": "Access: Invite"},
    "team.button.accessRoles": {"ja": "Access: Roles", "en": "Access: Roles"},
    "team.button.manageVc": {"ja": "VCを管理", "en": "Manage VC"},

    # --- team_ui.py: ephemeral response messages ---
    "team.msg.settingsUpdated": {"ja": "チーム設定を更新しました。", "en": "Updated team settings."},
    "team.history.settingsUpdatedTitle": {"ja": "チーム設定更新", "en": "Team settings updated"},
    "team.history.settingsUpdatedDesc": {"ja": "モード: `{mode}`\nチーム名: {names}", "en": "Mode: `{mode}`\nTeam names: {names}"},
    "team.history.teamAssignedTitle": {"ja": "チーム割り当て", "en": "Team assignment"},
    "team.history.recallTitle": {"ja": "呼び戻し", "en": "Recall"},
    "team.msg.myTeamUpdated": {"ja": "自分のチームを更新しました。", "en": "Updated your team."},
    "team.msg.noPermissionAssignOthers": {"ja": "他ユーザーの割り当て権限がありません。", "en": "You don't have permission to assign other users."},
    "team.msg.noAssignableParticipants": {"ja": "割り当て可能な参加者がいません。", "en": "There are no participants available to assign."},
    "team.msg.selectAssignTarget": {"ja": "次に割り当て対象のユーザーを選んでください。", "en": "Now select the user to assign."},
    "team.msg.teamAssignmentUpdated": {"ja": "チーム割り当てを更新しました。", "en": "Updated the team assignment."},
    "team.msg.recallExecuted": {"ja": "呼び戻しを実行しました。", "en": "Recall completed."},
    "team.msg.inviteUpdated": {"ja": "招待ユーザーを更新しました。", "en": "Updated invited users."},
    "team.msg.roleAccessUpdated": {"ja": "ロールによるアクセス設定を更新しました。", "en": "Updated role-based access settings."},
    "team.msg.selectMyTeam": {"ja": "所属したいチームを選択してください。", "en": "Select the team you want to join."},
    "team.msg.selectAssignTeam": {"ja": "割り当て先チームを選択してください。", "en": "Select the team to assign to."},
    "team.msg.splitExecuted": {"ja": "分割を実行しました。対象チーム数: {count}", "en": "Split completed. Teams affected: {count}"},
    "team.msg.assembleExecuted": {"ja": "集合を実行しました。対象 {count} 人。", "en": "Assemble completed. {count} member(s) affected."},
    "team.msg.noRecallableUsers": {"ja": "呼び戻せるユーザーがいません。", "en": "There are no users available to recall."},
    "team.msg.selectRecallTarget": {"ja": "呼び戻すユーザーを選んでください。", "en": "Select the user to recall."},
    "team.msg.accessSetPublic": {"ja": "VCのアクセスを公開に設定しました。", "en": "Set the VC access to public."},
    "team.msg.selectInviteUsers": {"ja": "招待するユーザーを選択してください。", "en": "Select the users to invite."},
    "team.msg.selectAllowedRoles": {"ja": "許可するロールを選択してください。", "en": "Select the allowed roles."},

    # --- bot.py: /team command responses ---
    "bot.command.teamDescription": {"ja": "チーム分けパネルを表示します。", "en": "Show the team-assignment panel."},
    "bot.msg.mustRunInServer": {"ja": "サーバー内で実行してください。", "en": "This command must be used in a server."},
    "bot.msg.mustJoinVcFirst": {"ja": "VCに参加してから実行してください", "en": "Join a voice channel before using this command."},
    "bot.msg.notManagedSession": {"ja": "このVCは管理対象セッションではありません。", "en": "This VC is not a managed session."},
    "bot.msg.mustRunInManagedText": {"ja": "管理対象VCのテキスト欄で実行してください。", "en": "Use this command in the managed VC's text channel."},
}


def t(key: str, locale: str | None, **kwargs: Any) -> str:
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    resolved_locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    text = entry.get(resolved_locale) or entry.get(DEFAULT_LOCALE) or next(iter(entry.values()))
    return text.format(**kwargs) if kwargs else text
