# VC Control

Discord サーバー向けのボイスチャンネル管理 Bot です。  
`Discord Bot + Web管理画面 + SQLite(config/stats分離)` を前提に、VC 自動作成・削除・通知・チーム分け・統計表示・OAuth ログインをまとめて扱います。

## 1. 全体設計

### アーキテクチャ

- `main.py`
  - DB 初期化
  - ログ初期化
  - 設定ロード
  - Web 起動
  - セットアップ済みなら Discord Bot も同時起動
- `config.db`
  - Bot 基本設定
  - OAuth 設定
  - サーバー別設定
  - 暗号化済み秘密情報
  - セッション復元用スナップショット
  - エラーログ
- `stats.db`
  - VC セッション履歴
  - ユーザー別通話時間
  - AFK 時間
  - 日別/時間帯別ロールアップ
  - ランキング集計
- `SessionManager`
  - VC 自動作成
  - 入退室イベント処理
  - 空室削除タイマー
  - セッション開始/終了
  - AFK 集計
  - チーム VC 管理
  - WebSocket 更新
- `FastAPI`
  - 初回セットアップ画面
  - Discord OAuth2 ログイン
  - 通常 VC 管理画面
  - Bot Owner 専用アドミン画面
  - `/ws` によるリアルタイム更新

### 保守方針

- 設定 DB と統計 DB を明確に分離
- DB 操作は repository 層へ隔離
- Bot イベント本体は薄くし、実処理は `SessionManager` に集約
- UI と API を分離し、Web 管理画面は将来 React 等へ差し替えやすい構成
- 秘密情報は `data/secret.key` による Fernet 暗号化保存

## 2. ディレクトリ構成

```text
vc-control/
├─ main.py
├─ requirements.txt
├─ README.md
├─ data/
│  └─ .gitkeep
└─ vc_control/
   ├─ __init__.py
   ├─ bootstrap.py
   ├─ bot.py
   ├─ logging_utils.py
   ├─ models.py
   ├─ repositories.py
   ├─ runtime.py
   ├─ security.py
   ├─ team_ui.py
   ├─ utils.py
   ├─ web.py
   ├─ static/
   │  ├─ app.js
   │  └─ style.css
   └─ templates/
      ├─ admin.html
      ├─ base.html
      ├─ dashboard.html
      ├─ login.html
      ├─ rankings.html
      ├─ setup.html
      ├─ stats_me.html
      └─ voice.html
```

## 3. 必要ライブラリ

- `discord.py`
- `fastapi`
- `uvicorn[standard]`
- `aiosqlite`
- `cryptography`
- `httpx`
- `jinja2`
- `python-multipart`
- `itsdangerous`

インストール例:

```bash
pip install -r requirements.txt
```

Pterodactyl などの自動デプロイ環境でも、起動前に必ず以下を実行してください。

```bash
pip install -r requirements.txt
```

`fastapi` のフォーム処理には `python-multipart`、`SessionMiddleware` には `itsdangerous` が必要です。どちらかが欠けると起動時 import / runtime error で停止します。

## 4. 各ファイルのコード

各ファイルのフルコードはリポジトリ内に配置済みです。主要ファイルは以下です。

- `main.py`: 起動エントリポイント
- `vc_control/runtime.py`: VC 管理・セッション・AFK・WebSocket 中核
- `vc_control/web.py`: セットアップ/OAuth/Web UI/API
- `vc_control/bot.py`: Discord Bot 本体
- `vc_control/team_ui.py`: `/team` のボタン/セレクト/モーダル
- `vc_control/repositories.py`: `config.db` / `stats.db` 操作

## 5. DB スキーマ

### `data/config.db`

- `app_settings`
  - `client_id`
  - `redirect_uri`
  - `base_url`
  - `owner_user_id`
  - `dashboard_host`
  - `dashboard_port`
  - `setup_completed`
- `secure_settings`
  - `bot_token`
  - `client_secret`
  - `session_secret`
- `guild_settings`
  - `guild_id`
  - `guild_name`
  - `managed_category_id`
  - `base_voice_channel_id`
  - `notification_channel_id`
  - `first_empty_notice_sec`
  - `final_delete_sec`
  - `team_mode`
  - `team_names_json`
  - `enabled`
- `session_snapshots`
  - Bot 再起動時のセッション復元用
- `error_logs`
  - `created_at`
  - `level`
  - `source`
  - `message`
  - `detail`

### `data/stats.db`

- `vc_sessions`
  - セッション開始/終了と要約
- `session_members`
  - セッション参加者ごとの通話/AFK 実績
- `user_totals`
  - ユーザー別累計
- `daily_user_stats`
  - 日別通話/AFK ロールアップ
- `hourly_user_stats`
  - 時間帯別ロールアップ

## 6. 初回セットアップ手順

1. Discord Developer Portal で Bot を作成する
2. このリポジトリで `pip install -r requirements.txt` を実行する
3. `python main.py` で起動する
4. 初回セットアップが未完了で、かつ `SETUP_PASSWORD` が未設定の場合は安全なランダムパスワードが自動生成され、Pterodactyl コンソールに表示される
5. `SETUP_PASSWORD` を環境変数で設定している場合は、その値が優先される
6. ブラウザで `http://127.0.0.1:8000/setup` または設定した `DASHBOARD_BASE_URL` の `/setup` を開く
7. 以下を入力して保存する
   - Bot Token
   - Discord Client ID
   - Discord Client Secret
   - Discord Redirect URI
   - Dashboard Base URL
   - Bot Owner Discord User ID
   - Dashboard Host / Port
8. セットアップ完了後は `/setup` とセットアップ用パスワードは無効になる
9. 一度プロセスを再起動する
10. `http://127.0.0.1:8000/login` から Discord OAuth2 ログインする
11. Bot Owner でログイン後、`/admin` からサーバー別設定を行う

## 7. 起動コマンド

### Pterodactyl / コンテナ環境での bind ルール

- `DASHBOARD_HOST` があればそれを優先します
- ポートは `SERVER_PORT` → `PORT` → `DASHBOARD_PORT` の順で優先します
- どれも未設定の場合、bind host は `0.0.0.0`、bind port は `49162` を使います
- `DASHBOARD_BASE_URL` は外部公開 URL 用であり、bind host / bind port とは別です
- `SETUP_PASSWORD` が未設定でも、初回セットアップ未完了なら自動生成されて Pterodactyl コンソールへ表示されます

例:

```bash
export DASHBOARD_HOST=0.0.0.0
export SERVER_PORT=49162
export DASHBOARD_BASE_URL=https://example.com
```

### PowerShell

```powershell
pip install -r requirements.txt
$env:DASHBOARD_HOST = "0.0.0.0"
$env:SERVER_PORT = "49162"
python main.py
```

### 固定のセットアップパスワードを使う場合

```powershell
pip install -r requirements.txt
$env:SETUP_PASSWORD = "your-setup-password"
python main.py
```

### 初回セットアップ後の再起動

```powershell
pip install -r requirements.txt
python main.py
```

## 8. Discord 側で必要な設定

### Bot Intents

Developer Portal の Bot タブで以下を有効化してください。

- `SERVER MEMBERS INTENT`
- `MESSAGE CONTENT INTENT`
- `GUILD PRESENCES` は不要

コード上で使用している主な Intent:

- `guilds`
- `members`
- `voice_states`
- `messages`
- `message_content`

### Bot に必要な権限

最低限、以下を推奨します。

- `View Channels`
- `Manage Channels`
- `Move Members`
- `Mute Members`
- `Deafen Members`
- `Send Messages`
- `Embed Links`
- `Read Message History`
- `Mention Everyone` は不要

### OAuth2 Redirect URI

Developer Portal の OAuth2 設定へ、セットアップ画面で入力するものと同じ URI を登録してください。

例:

```text
http://127.0.0.1:8000/callback
```

### OAuth2 URL で Bot を招待する際の推奨 Scope

- `bot`
- `applications.commands`

## 9. 動作確認チェックリスト

- 自動生成または環境変数で指定した `SETUP_PASSWORD` で `/setup` が開ける
- セットアップ後に `/setup` が無効化される
- Bot Owner だけが `/admin` を開ける
- 基点 VC 入室で `{表示名}のVC` が自動作成または再利用される
- 管理対象カテゴリ内 VC の入退室通知が Voice Channel テキスト欄へ出る
- 空室 VC で削除予告と最終削除が動く
- 再入室で削除キャンセルが出る
- `/team` でパネル表示、自己割当、他者割当、分割、集合、呼び戻しができる
- チーム VC が `{元VC名}-{チーム名}` で作成される
- Bot 再起動後に進行中セッションが復元される
- `/dashboard/me` にアクセスできる
- `/dashboard/voice/{guild_id}/{root_channel_id}` で VC 状態が見られる
- `/dashboard/stats/me` に日別バー、時間帯ヒートマップ、通話 vs AFK 比率が出る
- `/dashboard/rankings` に全体/サーバー別ランキングが出る
- `config.db` と `stats.db` が別ファイルで作成される
- `error_logs` に例外ログが保存される

## 補足

- 設定変更のうち `Bot Token` / `Client Secret` / `Client ID` / Redirect URI の反映は再起動前提です。
- `settings.json` は使っていません。
- 将来 MySQL へ寄せる場合は `repositories.py` を差し替える構成を想定しています。
