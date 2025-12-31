import discord
from datetime import datetime
from .time_utils import fmt_jst, fmt_duration


def embed_join(member):
    e = discord.Embed(
        description=f"{member.display_name} がボイスチャンネルに接続しました。",
        color=0x2ECC71
    )
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    return e


def embed_leave(member):
    e = discord.Embed(
        description=f"{member.display_name} がボイスチャンネルから切断しました。",
        color=0xE74C3C
    )
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    return e


def embed_empty_notice():
    return discord.Embed(
        description="全員が退出したため、まもなく削除されます。",
        color=0xE74C3C
    )


def embed_notice_start(member, start_dt: datetime):
    unix = int(start_dt.timestamp())
    return discord.Embed(
        title=f"{member.display_name}がVCを開始しました。",
        description=f"VC開始時刻：{fmt_jst(start_dt)} (<t:{unix}:R>)",
        color=0x2ECC71
    )


def embed_notice_end(vc_name, started_at, ended_at, participants):
    total = int((ended_at - started_at).total_seconds())
    dur = fmt_duration(total)

    lines = []
    for uid, p in participants.items():
        sec = p["total_sec"]
        lines.append(f"- {p['name']}（参加時間: {fmt_duration(sec)}）")

    block = "\n".join(lines) if lines else "- (該当者なし)"

    return discord.Embed(
        title=f"{vc_name}が終了しました。",
        description=(
            f"VC開始時刻：{fmt_jst(started_at)}\n"
            f"VC終了時刻：{fmt_jst(ended_at)}\n"
            f"VC継続時間：{dur}\n"
            f"参加ユーザー：\n{block}"
        ),
        color=0xE74C3C
    )


def embed_manage_panel(vc_name: str, manage_url: str, starter_name: str | None = None):
    description = (
        f"{vc_name} の管理ページが利用できます。\n"
        f"[管理画面を開く]({manage_url}) からVC名・最大人数・ビットレートを変更できます。"
    )
    if starter_name:
        description += f"\n開始ユーザー: {starter_name}"

    return discord.Embed(
        title="VC管理パネル", description=description, color=0x5865F2
    )


def embed_team_overview(vc_name: str, assignments: dict, starter_name: str | None = None):
    lines = []
    for label in ["A", "B", "C", "D"]:
        members = assignments.get(label) or []
        label_block = "、".join(members) if members else "-"
        lines.append(f"{label}チーム: {label_block}")

    description = "\n".join(lines)
    description += "\n\nリアクションでチームを選択できます。"
    description += "\n🔀 でチーム別VCへ分割、🏠 で集合します。"
    if starter_name:
        description += f"\n開始ユーザー: {starter_name}"

    return discord.Embed(
        title=f"{vc_name} のチーム編成", description=description, color=0x5865F2
    )
