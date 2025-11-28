# ================================
# VC入退室通知（Embed）＋ VCテキストでの@メンションをDMで通知
# ＋ 通知チャンネル（NOTICE_CHANNEL_ID）へ VC開始/終了のサマリEmbed送信
# 依存: Pycord推奨（pip install -U py-cord）
# ================================

import json
import logging
import asyncio
import discord
from discord.ext import commands
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

# ===== ログ設定 =====
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vc-bot")

# ===== 設定ファイル読み込み & バリデーション =====
SETTINGS_FILE = Path("settings.json")
if not SETTINGS_FILE.exists():
    raise FileNotFoundError("settings.json が見つかりません。")

with SETTINGS_FILE.open("r", encoding="utf-8") as f:
    config = json.load(f)

def _require(cfg: Dict[str, Any], key: str, typ, cast=int):
    if key not in cfg:
        raise KeyError(f"settings.json に {key} がありません。")
    val = cfg[key]
    if typ is int:
        try:
            return cast(val)
        except Exception:
            raise TypeError(f"{key} は数値(ID)で指定してください。")
    return val

TOKEN: str = _require(config, "TOKEN", str, cast=str)
BASE_VC_ID: int = _require(config, "BASE_VC_ID", int)
VC_CATEGORY_ID: int = _require(config, "VC_CATEGORY_ID", int)
NOTICE_CHANNEL_ID: int = _require(config, "NOTICE_CHANNEL_ID", int)

# 無人→通知→削除までの秒数（合計 30 秒が既定）
FIRST_EMPTY_NOTICE_SEC: int = int(config.get("FIRST_EMPTY_NOTICE_SEC", 10))
FINAL_DELETE_SEC: int = int(config.get("FINAL_DELETE_SEC", 20))

# ===== データ（簡易 JSON: 作成VCの記録） =====
DATA_FILE = Path("data.json")
if not DATA_FILE.exists():
    DATA_FILE.write_text(json.dumps({"created_vcs": []}, ensure_ascii=False, indent=2), encoding="utf-8")

_data_lock = asyncio.Lock()
vc_cleanup_tasks: Dict[int, asyncio.Task] = {}

async def load_data() -> Dict[str, Any]:
    async with _data_lock:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)

async def save_data(data: Dict[str, Any]):
    async with _data_lock:
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# ===== Bot初期化 =====
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.message_content = True  # VCテキストのメッセージ内容を扱うため
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== ユーティリティ（時刻） =====
JST = timezone(timedelta(hours=9))

def fmt_jst_human(dt: datetime) -> str:
    # 例: 8月12日 17:00
    return dt.astimezone(JST).strftime("%-m月%-d日 %H:%M") if hasattr(dt, "astimezone") else dt.strftime("%m月%d日 %H:%M")

def fmt_duration(total_seconds: int) -> str:
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    parts = []
    if h: parts.append(f"{h}時間")
    if m or (h and s): parts.append(f"{m}分")
    parts.append(f"{s}秒")
    return "".join(parts)

def in_target_category(ch: Optional[discord.abc.GuildChannel]) -> bool:
    return isinstance(ch, discord.VoiceChannel) and ch.category and ch.category.id == VC_CATEGORY_ID

def get_notice_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    ch = guild.get_channel(NOTICE_CHANNEL_ID)
    return ch if isinstance(ch, discord.TextChannel) else None

# ===== VCテキスト向け Embed（入退室） =====
def build_embed_for_event(member: Optional[discord.abc.User], event_type: str) -> discord.Embed:
    """
    event_type: "join" | "leave" | "empty_notice"
    - join: 緑/「接続しました。」
    - leave: 赤/「切断しました。」
    - empty_notice: 赤/「全員が退出したため、まもなく削除されます。」
    （タイトル・時間フィールドは付けない仕様）
    """
    if event_type == "join":
        color = 0x2ECC71
        action_text = "接続しました。"
    elif event_type == "leave":
        color = 0xE74C3C
        action_text = "切断しました。"
    else:
        color = 0xE74C3C
        action_text = "全員が退出したため、まもなく削除されます。"

    description = (
        f"{member.display_name} がボイスチャンネルに{action_text}"
        if member and event_type in ("join", "leave")
        else action_text
    )

    embed = discord.Embed(description=description, color=color)
    if member and hasattr(member, "display_avatar") and event_type in ("join", "leave"):
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    return embed

async def send_embed_to_vc(vc: discord.VoiceChannel, embed: discord.Embed):
    """VCのテキストメッセージ欄に送信（Pycord 等で vc.send が使える前提）"""
    try:
        if hasattr(vc, "send") and callable(getattr(vc, "send")):
            await vc.send(embed=embed)
        else:
            raise NotImplementedError("VoiceChannel.send が未対応のライブラリです。Pycord などをご利用ください。")
    except Exception as e:
        log.warning(f"[VCテキスト送信失敗] VC={vc.name}: {e}")

# ===== VC開始/終了 通知チャンネル向け Embed =====
def build_notice_start_embed(starter: discord.Member, started_at: datetime) -> discord.Embed:
    unix = int(started_at.replace(tzinfo=timezone.utc).timestamp())
    human = fmt_jst_human(started_at)
    title = f"{starter.display_name}がVCを開始しました。"
    desc = f"VC開始時刻：{human} (<t:{unix}:R>)"
    embed = discord.Embed(title=title, description=desc, color=0x2ECC71)
    if hasattr(starter, "display_avatar"):
        embed.set_author(name=starter.display_name, icon_url=starter.display_avatar.url)
    return embed

def build_notice_end_embed(vc: discord.VoiceChannel, started_at: datetime, ended_at: datetime, participants: Dict[int, Dict[str, Any]]) -> discord.Embed:
    title = f"{vc.name}が終了しました。"
    start_h = fmt_jst_human(started_at)
    end_h = fmt_jst_human(ended_at)
    total = int((ended_at - started_at).total_seconds())
    dur = fmt_duration(total)

    # 参加者一覧を整形
    if participants:
        lines = []
        for uid, p in participants.items():
            name = p.get("name", f"UID:{uid}")
            sec = int(p.get("total_sec", 0))
            # joined_at が残っていたら（理論上終了時は全員抜け済）安全側で加算
            joined_at = p.get("joined_at")
            if isinstance(joined_at, datetime):
                sec += int((ended_at - joined_at).total_seconds())
            lines.append(f"- {name}（参加時間: {fmt_duration(sec)}）")
        members_block = "\n".join(lines)
    else:
        members_block = "- (該当者なし)"

    desc = (
        f"VC開始時刻：{start_h}\n"
        f"VC終了時刻：{end_h}\n"
        f"VC継続時間：{dur}\n"
        f"参加したユーザー：\n{members_block}"
    )
    embed = discord.Embed(title=title, description=desc, color=0xE74C3C)
    return embed

# ===== VCセッション状態（メモリ管理） =====
# sessions[vc_id] = {
#   "start": datetime(UTC),
#   "starter_id": int,
#   "notice_msg_id": Optional[int],
#   "participants": {
#       user_id: { "name": str, "total_sec": int, "joined_at": Optional[datetime(UTC)] }
#   }
# }
sessions: Dict[int, Dict[str, Any]] = {}

def ensure_session(vc: discord.VoiceChannel, starter: discord.Member, now_utc: datetime) -> Dict[str, Any]:
    s = sessions.get(vc.id)
    if s is None:
        s = {
            "start": now_utc,
            "starter_id": starter.id,
            "notice_msg_id": None,
            "participants": {}
        }
        sessions[vc.id] = s
    return s

def participant_join(vc_id: int, member: discord.Member, now_utc: datetime):
    sess = sessions.get(vc_id)
    if not sess:
        return
    parts = sess["participants"]
    u = parts.get(member.id)
    if u is None:
        u = {"name": member.display_name, "total_sec": 0, "joined_at": now_utc}
        parts[member.id] = u
    else:
        # 既に joined_at があるなら何もしない、無ければ入室時刻を記録
        if u.get("joined_at") is None:
            u["joined_at"] = now_utc
        # 表示名を最新化
        u["name"] = member.display_name

def participant_leave(vc_id: int, member: discord.Member, now_utc: datetime):
    sess = sessions.get(vc_id)
    if not sess:
        return
    parts = sess["participants"]
    u = parts.get(member.id)
    if not u:
        # 未登録だが leave だけ飛んできたケース：無視
        return
    joined_at = u.get("joined_at")
    if isinstance(joined_at, datetime):
        u["total_sec"] = int(u.get("total_sec", 0)) + int((now_utc - joined_at).total_seconds())
        u["joined_at"] = None
    # 表示名を最新化
    u["name"] = member.display_name

# ===== VCテキストでの@メンション → DM送信 =====
def extract_non_mention_text(message: discord.Message) -> str:
    text = message.content or ""
    if not text:
        return ""
    for user in message.mentions:
        pid = str(user.id)
        text = text.replace(f"<@{pid}>", "").replace(f"<@!{pid}>", "")
    cleaned = " ".join(text.split())
    return cleaned

async def dm_mentioned_user(from_member: discord.Member, mentioned: discord.Member, vc: discord.VoiceChannel, message: discord.Message):
    color = 0x5865F2
    title = f"🔔 {from_member.display_name}がVCであなたを呼んでいます。"
    desc = f"{from_member.display_name} さんが **{vc.name}** であなたをメンションしました。"

    embed = discord.Embed(title=title, description=desc, color=color)
    if hasattr(from_member, "display_avatar"):
        embed.set_author(name=from_member.display_name, icon_url=from_member.display_avatar.url)

    extra = extract_non_mention_text(message)
    if extra:
        embed.add_field(name="メッセージ内容", value=extra[:1000], inline=False)

    try:
        jump = message.jump_url
        if jump:
            embed.add_field(name="リンク", value=f"[メッセージへジャンプ]({jump})", inline=False)
    except Exception:
        pass

    try:
        await mentioned.send(embed=embed)
    except Exception as e:
        err = f"⚠️ {mentioned.mention} へDMを送信できませんでした（DM拒否/フレンドのみ 等）。"
        try:
            if hasattr(vc, "send") and callable(getattr(vc, "send")):
                await vc.send(err)
        except Exception as ce:
            log.warning(f"[VCへエラー投稿も失敗] {ce}")
        log.warning(f"[DM送信失敗] to={mentioned} reason={e}")

# ===== 個人VC作成 =====
async def ensure_personal_vc(member: discord.Member) -> discord.VoiceChannel:
    guild = member.guild
    category = guild.get_channel(VC_CATEGORY_ID)
    if category is None or not isinstance(category, discord.CategoryChannel):
        raise RuntimeError(f"カテゴリー(ID={VC_CATEGORY_ID})が見つかりません。")

    name = f"{member.display_name}のVC"
    for ch in category.voice_channels:
        if ch.name == name:
            return ch

    new_vc = await guild.create_voice_channel(name=name, category=category, reason="個人VCの自動作成")
    data = await load_data()
    data["created_vcs"].append(new_vc.id)
    await save_data(data)
    return new_vc

# ===== 無人→削除スケジュール（VC自体の削除） =====
async def schedule_vc_cleanup(vc: discord.VoiceChannel):
    try:
        await asyncio.sleep(FIRST_EMPTY_NOTICE_SEC)
        if len(vc.members) == 0:
            await send_embed_to_vc(vc, build_embed_for_event(member=None, event_type="empty_notice"))

        await asyncio.sleep(FINAL_DELETE_SEC)
        if len(vc.members) == 0:
            try:
                data = await load_data()
                if vc.id in data.get("created_vcs", []):
                    data["created_vcs"].remove(vc.id)
                    await save_data(data)

                await vc.delete(reason=f"{FIRST_EMPTY_NOTICE_SEC+FINAL_DELETE_SEC}秒間無人のため削除")
                log.info(f"VC削除: {vc.name}")
            except Exception as e:
                log.warning(f"VC削除処理失敗: {e}")
    except asyncio.CancelledError:
        log.debug(f"削除スケジュールキャンセル: {vc.name}")
        raise
    finally:
        vc_cleanup_tasks.pop(vc.id, None)

# ===== イベント: 起動 =====
@bot.event
async def on_ready():
    log.info(f"Botログイン成功: {bot.user} (ID: {bot.user.id})")

# ===== イベント: VC入退室 =====
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    # ミュート/画面共有などは除外
    if before.channel == after.channel:
        return

    now_utc = datetime.now(timezone.utc)

    # BASE_VC: 個人VC作成＆移動のみ、通知なし
    if after.channel and after.channel.id == BASE_VC_ID:
        try:
            vc = await ensure_personal_vc(member)
            if member.voice and member.voice.channel and member.voice.channel.id != vc.id:
                await member.move_to(vc, reason="個人VCへ移動")
        except Exception as e:
            log.warning(f"個人VC作成/移動失敗: {e}")
        return

    # ======== 入室側処理 ========
    if after.channel and in_target_category(after.channel) and after.channel.id != BASE_VC_ID:
        vc_after: discord.VoiceChannel = after.channel

        # VCテキストにも入室Embed（従来機能）
        await send_embed_to_vc(vc_after, build_embed_for_event(member, "join"))

        # セッション開始判定（入室直後にメンバー数が1なら = 開始）
        if len(vc_after.members) == 1:
            sess = ensure_session(vc_after, member, now_utc)
            # 参加者に入室登録
            participant_join(vc_after.id, member, now_utc)

            # 通知チャンネルへ「開始」Embed
            notice = get_notice_channel(member.guild)
            if notice:
                try:
                    msg = await notice.send(embed=build_notice_start_embed(member, sess["start"]))
                    sess["notice_msg_id"] = msg.id
                except Exception as e:
                    log.warning(f"[開始通知送信失敗] {e}")
            else:
                log.warning("NOTICE_CHANNEL_ID が無効、またはテキストチャンネルではありません。")
        else:
            # 既存セッションがあれば参加者に記録
            if vc_after.id in sessions:
                participant_join(vc_after.id, member, now_utc)

        # 入室で削除キャンセル（VC自動削除機構）
        t = vc_cleanup_tasks.get(vc_after.id)
        if t and not t.done():
            t.cancel()

    # ======== 退室側処理 ========
    if before.channel and in_target_category(before.channel) and before.channel.id != BASE_VC_ID:
        vc_before: discord.VoiceChannel = before.channel

        # VCテキストにも退室Embed（従来機能）
        await send_embed_to_vc(vc_before, build_embed_for_event(member, "leave"))

        # 参加者の滞在時間を記録
        if vc_before.id in sessions:
            participant_leave(vc_before.id, member, now_utc)

        # 無人ならセッション終了 + 通知送信
        if len(vc_before.members) == 0:
            sess = sessions.pop(vc_before.id, None)
            if sess:
                started_at: datetime = sess["start"]
                ended_at: datetime = now_utc

                # 開始Embedを削除
                notice = get_notice_channel(member.guild)
                if notice and sess.get("notice_msg_id"):
                    try:
                        msg = await notice.fetch_message(sess["notice_msg_id"])
                        await msg.delete()
                    except Exception as e:
                        log.warning(f"[開始Embed削除失敗] {e}")

                # 終了Embedを送信
                if notice:
                    try:
                        await notice.send(embed=build_notice_end_embed(vc_before, started_at, ended_at, sess.get("participants", {})))
                    except Exception as e:
                        log.warning(f"[終了通知送信失敗] {e}")

        # 無人ならVC削除スケジュール（従来機能）
        if len(vc_before.members) == 0 and vc_before.id not in vc_cleanup_tasks:
            task = asyncio.create_task(schedule_vc_cleanup(vc_before))
            vc_cleanup_tasks[vc_before.id] = task

# ===== イベント: VCテキストのメッセージ監視（@メンション→DM） =====
@bot.event
async def on_message(message: discord.Message):
    # Bot自身や他Botは無視
    if message.author.bot:
        return

    # VCのテキストメッセージ欄のみ対象（Pycordでは VoiceChannel も Messageable）
    ch = message.channel
    if not isinstance(ch, discord.VoiceChannel):
        return

    # @everyone/@here は無視してVCテキストに警告
    if getattr(message, "mention_everyone", False):
        try:
            if hasattr(ch, "send") and callable(getattr(ch, "send")):
                await ch.send("⚠️ `@everyone` / `@here` のメンションはDM転送されません。")
        except Exception as e:
            log.warning(f"[everyone警告送信失敗] {e}")
        return

    # 宛先ユーザーを抽出（重複は1回にし、Botアカウントは除外）
    targets = []
    seen_ids = set()
    for m in message.mentions:
        if m.bot:
            continue
        if m.id not in seen_ids:
            targets.append(m)
            seen_ids.add(m.id)

    if not targets:
        return  # ユーザーへのメンションが無ければ終わり

    # それぞれにDM Embedを送信（失敗時はVC側にエラー）
    for target in targets:
        try:
            await dm_mentioned_user(from_member=message.author, mentioned=target, vc=ch, message=message)
        except Exception as e:
            # 念のため二重にVCへエラー通知
            try:
                await ch.send(f"⚠️ {target.mention} へのDM送信に失敗しました。")
            except Exception as ce:
                log.warning(f"[VCへエラー投稿も失敗] {ce}")
            log.warning(f"[DM送信例外] {e}")

    # コマンド処理等のため（他Cogがある場合）
    await bot.process_commands(message)

# ===== 終了時クリーンアップ =====
async def _shutdown_cleanup():
    for _, task in list(vc_cleanup_tasks.items()):
        if not task.done():
            task.cancel()
    vc_cleanup_tasks.clear()

def main():
    try:
        bot.run(TOKEN)
    finally:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_shutdown_cleanup())
        else:
            loop.run_until_complete(_shutdown_cleanup())

if __name__ == "__main__":
    main()
