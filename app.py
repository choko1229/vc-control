import json
import logging
import asyncio
import discord
from discord.ext import commands
import os

# ログ設定
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vc-bot")

# 設定ファイル読み込み
with open("settings.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["TOKEN"]
BASE_VC_ID = config["BASE_VC_ID"]
VC_CATEGORY_ID = config["VC_CATEGORY_ID"]

# データ保存用ファイル
DATA_FILE = "data.json"

# 初期データ
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"created_vcs": []}, f, ensure_ascii=False, indent=2)

# データ読み書き関数
def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 削除予定のVCタスク管理
vc_cleanup_tasks = {}

# Intents設定
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ユーティリティ
def in_target_category(ch):
    return (
        isinstance(ch, discord.VoiceChannel) and
        ch.category and ch.category.id == VC_CATEGORY_ID
    )

async def safe_send_to_vc_text(vc, content):
    try:
        await vc.send(content)
    except Exception as e:
        log.warning(f"VCテキスト送信失敗: {e}")

async def ensure_personal_vc(member):
    guild = member.guild
    category = guild.get_channel(VC_CATEGORY_ID)
    name = f"{member.display_name}のVC"

    for ch in category.voice_channels:
        if ch.name == name:
            return ch

    # 作成
    new_vc = await guild.create_voice_channel(name=name, category=category)
    data = load_data()
    data["created_vcs"].append(new_vc.id)
    save_data(data)
    return new_vc

async def schedule_vc_cleanup(vc):
    await asyncio.sleep(10)
    if len(vc.members) == 0:
        await safe_send_to_vc_text(vc, "全員切断されました。")

    await asyncio.sleep(20)
    if len(vc.members) == 0:
        try:
            data = load_data()
            if vc.id in data["created_vcs"]:
                data["created_vcs"].remove(vc.id)
                save_data(data)
            await vc.delete(reason="30秒経過後に削除")
            log.info(f"VC削除: {vc.name}")
        except Exception as e:
            log.warning(f"VC削除失敗: {e}")
    vc_cleanup_tasks.pop(vc.id, None)

@bot.event
async def on_ready():
    log.info(f"Botログイン成功: {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # 個人VC作成＆移動
    if after.channel and after.channel.id == BASE_VC_ID:
        vc = await ensure_personal_vc(member)
        if member.voice and member.voice.channel.id != vc.id:
            await member.move_to(vc, reason="個人VCへ移動")

    # 接続通知
    if after.channel and in_target_category(after.channel) and after.channel.id != BASE_VC_ID:
        await safe_send_to_vc_text(after.channel, f"{member.display_name}が接続しました。")

    # 切断通知
    if before.channel and in_target_category(before.channel) and before.channel.id != BASE_VC_ID:
        if not after.channel or after.channel.id != before.channel.id:
            await safe_send_to_vc_text(before.channel, f"{member.display_name}が切断しました。")

        # 誰もいなければ削除スケジュール
        if len(before.channel.members) == 0:
            if before.channel.id not in vc_cleanup_tasks:
                task = asyncio.create_task(schedule_vc_cleanup(before.channel))
                vc_cleanup_tasks[before.channel.id] = task

    # 削除キャンセル
    if after.channel and in_target_category(after.channel) and after.channel.id != BASE_VC_ID:
        if after.channel.id in vc_cleanup_tasks:
            task = vc_cleanup_tasks.pop(after.channel.id)
            task.cancel()
            await safe_send_to_vc_text(after.channel, f"{member.display_name}が接続したため、削除をキャンセルしました。")

bot.run(TOKEN)
