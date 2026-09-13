<p align="center"><a href="README.md">中文</a> · <a href="README_en.md">English</a> · <a href="README_ru.md">Русский</a> · <strong>日本語</strong></p>

<div align="center">

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/logo.png" width="120" alt="Schedule Assistant Logo" />

# 🗓️ Schedule Assistant — スケジュールリマインダー

**あなたの頼れるスケジュール執事** — 朝の配信 · 習慣リマインダー · LLM によるスケジュール管理 · Apple カレンダー双方向同期 · Notion ToDo 同期

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues)

</div>

> 🎨 本プロジェクトは AI によって作成されました · プラグインのロゴは Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279) から

---

## ✨ 主な機能

| 機能 | 説明 |
|------|------|
| 🌤️ **毎日の朝の配信** | 天気 + 今日の予定 + Notion ToDo + 夜更かし検出。起床に必要な情報を 1 通のメッセージで |
| ⏰ **スマートな習慣リマインダー** | 入浴 / 睡眠 / 水分補給の定時リマインダー。後回しや一時的な時刻変更も可能 |
| 🤖 **LLM によるスケジュール管理** | 話すだけで予定を管理：追加 / 削除 / 照会 / 変更、自然言語での日時解析 |
| 🔄 **Apple カレンダー双方向同期** | iCloud CalDAV の読み書き、自動的な重複排除と増分更新 |
| 📝 **Notion ToDo 同期** | 朝の配信で DDL カウントダウン（残り N 日 / 今日が締め切り / 期限超過） |
| 🎨 **マルチプラットフォーム Markdown レンダリング** | QQ 公式はネイティブテーブル対応、Onebot などのプラットフォームは自動的にプレーンテキストへフォールバック |

---

## 📖 機能概要

### 毎日の朝の配信
毎朝自動で配信（時刻は設定可能）。起床に必要な情報を 1 通のメッセージで届けます：

<img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/docs/briefing_example.png" alt="朝の配信の例" width="480" />

### 習慣リマインダー

| 習慣 | デフォルト時刻 | 説明 |
|------|---------|------|
| 🚿 入浴リマインダー | 22:00 | 後回しや一時的な時刻変更が可能 |
| 😴 睡眠リマインダー | 23:00 | スマートな就寝促し、遅いとツッコミ入り |
| 💧 水分補給リマインダー | 90 分ごと | 9:30–21:30 の繰り返し、スキップ可能 |
| 📅 予定のスマートリマインダー | N 分前 | **LLM が生成**する自然言語リマインダー、文脈を考慮 |

### Apple iCloud カレンダー双方向同期

**読み取り（Apple → ローカル）：**
- iCloud カレンダーの予定を定期的にローカルストレージへ取得
- 追加 / 変更 / 削除を自動同期。Apple カレンダーを正とする

**書き込み（ローカル → Apple）：**
- ボットで追加した予定を指定の Apple カレンダーへ自動書き込み
- 予定の UID を記録し、以後の同期識別と重複排除に対応

**接続に必要なもの：**
- `username` — Apple ID のメールアドレス（例：`xxx@icloud.com`）
- `app_password` — **アプリ専用パスワード**（[appleid.apple.com](https://appleid.apple.com) で生成します。ログインパスワードではありません）
- `calendar_id` — 対象カレンダーの UUID。空欄なら先頭のカレンダー。UUID は Apple カレンダーの CalDAV サーバーアドレス（`…/calendars/<UUID>/` の形式）からコピーして入力します

### Notion ToDo 同期
Notion のタスクは毎朝の配信で DDL カウントダウン付き（残り N 日 / 今日が締め切り / 期限超過）で一覧表示されます。事前に Maton Gateway を中継層として設定する必要があります。

### Markdown レンダリング
すべての定時配信（朝の配信 / 習慣 / 予定リマインダー）は統一レンダリングパイプラインを通り、プラットフォームに応じて自動的にフォールバックします：
- **native** — md をネイティブ解析するプラットフォーム（qq_official、discord、telegram など）には原文のまま送信
- **plain** — ネイティブ md 非対応のプラットフォームは自動的に strip され、プレーンテキストになります

QQ のネイティブテーブルは整列された行として自動レンダリングされ、追加設定は不要です。設定で無効化や強制切り替えも可能です。

---

## 🚀 クイックスタート

### ステップ 1：Schedule Assistant のインストール

**方法 1：プラグインマーケット**
- AstrBot WebUI → プラグインマーケット → `schedule_assistant` を検索

**方法 2：手動インストール**
1. プラグインフォルダーを `/AstrBot/data/plugins/` に入れる
2. AstrBot を再起動
3. 管理パネルで必要に応じて各パラメーターを設定

> 💡 主要な依存関係は AstrBot 環境に同梱済みで、追加インストールは不要です。

### ステップ 2：最小構成（すべての定時リマインダーを動かす）

WebUI のプラグイン設定 → **基本設定** → `user_ids` に 1 行入力するだけです：

```
プラットフォームID:FriendMessage:ユーザーID
```

`プラットフォーム ID:セッションタイプ:ユーザー ID`（UMO 形式）の 1 行で「誰にリマインドするか + どのプラットフォームから送るか」を解決します。QQ 番号だけの入力も可能で、自動的に個人チャットとして送信されます。

### ステップ 3（任意）：Notion 同期の設定

1. [Maton](https://www.maton.ai/) で Notion を接続（OAuth2 方式）し、**Maton API Key** を生成
2. [api-gateway-skill](https://github.com/maton-ai/api-gateway-skill) をダウンロードし、設定に Maton API Key を入力
3. AstrBot 管理パネル → **Skills** → api-gateway-skill をアップロードして有効化

---

## ⚙️ 設定項目の説明

### 基本設定

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `persona_id` | string | `""` | LLM パーソナ ID（設定ファイルの `persona_id` に対応）。空欄ならセッションから自動取得 |
| `user_nickname` | string | `""` | ユーザーのニックネーム。空欄の場合、配信では「主人」と呼びかけます |
| `user_ids` | list | `[]` | 自動リマインダーを受け取るユーザー ID のリスト（QQ 番号またはプラットフォーム UID）。UMO 形式（`プラットフォーム ID:セッションタイプ:ユーザー ID`）で入力すればプラットフォームルーティングも同時に設定できます |

### 予定リマインダー設定

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `enable_schedule_reminder` | bool | `false` | 予定の LLM スマートリマインダーのスイッチ（デフォルトはオフ） |
| `schedule_reminder_minutes` | int | `10` | 予定開始の何分前にリマインドするか（終日の予定は対象外） |
| `schedule_reminder_check_interval` | int | `5` | 予定リマインダーのスキャン間隔（分）。リードタイムの 1/3〜1/2 を推奨（例：10 分前なら 3〜5 分間隔）、最小値は 2 分 |

### 習慣リマインダー設定

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `enable_morning_report` | bool | `true` | 朝の配信のスイッチ |
| `morning_report_time` | string | `09:00` | 朝の配信の送信時刻（HH:MM） |
| `enable_bath_reminder` | bool | `true` | 入浴リマインダーのスイッチ |
| `bath_time` | string | `22:00` | 入浴リマインダーの時刻 |
| `enable_sleep_reminder` | bool | `true` | 睡眠リマインダーのスイッチ |
| `sleep_time` | string | `23:00` | 睡眠リマインダーの時刻 |
| `enable_water_reminder` | bool | `true` | 水分補給リマインダーのスイッチ |
| `water_interval` | int | `90` | 水分補給の間隔（分） |
| `water_start_time` | string | `09:30` | 水分補給の開始時刻 |
| `water_end_time` | string | `21:30` | 水分補給の終了時刻 |

### カレンダー同期設定

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `enable_apple_calendar_sync` | bool | `false` | Apple カレンダー双方向同期のスイッチ |
| `apple_calendar_sync_interval` | int | `30` | Apple カレンダーの同期間隔（分） |
| `apple_calendar.username` | string | - | Apple ID のメールアドレス |
| `apple_calendar.app_password` | string | - | **アプリ専用パスワード**（ログインパスワードではありません） |
| `apple_calendar.calendar_id` | string | - | 対象カレンダーの UUID。空欄なら先頭。UUID は Apple カレンダーの CalDAV サーバーアドレス（`…/calendars/<UUID>/`）からコピー |
| `webcal_urls` | list | `[]` | WebCal 共有カレンダーのリンク |

> 💡 **WebCal 購読のセキュリティ**：`webcal_urls` は公開の `https://` 購読アドレスのみを受け付けます（`webcal://` は自動的に `https://` に変換）。プラグインは `localhost`、内部ネットワーク（`192.168.x` / `10.x` など）、クラウドメタデータ（`169.254.169.254`）などのアドレスを拒否します（SSRF 対策）。内部ネットワークやローカルのアドレスは入力しないでください。

> 書き込みはトップレベルの `enable_apple_calendar_sync` で一括制御されます。有効にすると、ローカルで作成 / 削除した予定が Apple カレンダーへ自動同期されます。

### 外部サービス設定

| 設定項目 | 型 | 説明 |
|--------|------|------|
| `maton_api_key` | string | Maton API Key（Notion 機能に必須） |
| `notion_db_ids` | list | Notion データベース ID のリスト。形式：`["仕事:xxx", "読書:yyy"]` — 接頭辞は任意のカテゴリ名で構いません |
| `weather_api_key` | string | Seniverse の API キー（[seniverse.com](https://seniverse.com)） |
| `weather_city` | string | 天気を取得する都市（デフォルト：北京） |

### メッセージレンダリング設定

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `markdown_enabled` | bool | `true` | グローバルの Markdown レンダリングスイッチ。オフにするとプレーンテキストへフォールバック |
| `markdown_native_platforms` | list | `[]` | Markdown をネイティブ解析するプラットフォーム型名の追加（インスタンス ID は無効） |
| `qq_markdown_enabled` | bool | 空欄 | QQ プラットフォームのスイッチ：空欄ならグローバル設定に従う。`false` で QQ はネイティブ md を強制オフ |

### リマインダー Prompt テンプレート

| 設定項目 | 型 | デフォルト | 説明 |
|--------|------|------|------|
| `prompt_morning` | string | `""` | 朝の配信テンプレート。プレースホルダー：`{username} {date} {weekday} {weather_current} {weather_forecast} {agenda} {notion_todos} {late_night}` |
| `prompt_bath` | string | `""` | 入浴リマインダーテンプレート。プレースホルダー：`{current_time} {default_time} {history}` |
| `prompt_sleep` | string | `""` | 睡眠リマインダーテンプレート。プレースホルダー：`{current_time} {default_time} {is_late} {history}` |
| `prompt_water` | string | `""` | 水分補給リマインダーテンプレート。プレースホルダー：`{current_time} {history}` |
| `prompt_schedule` | string | `""` | 予定リマインダーテンプレート。プレースホルダー：`{item_title} {time_label} {ahead_label} {item_context} {conv_history}` |

> テンプレートを空欄にすると内蔵のデフォルト（`prompt_config.py` 参照）が使われます。リマインダーの口調をカスタマイズしたい場合に入力してください。`{変数名}` 形式のプレースホルダーに対応しています。

### クイック設定テンプレート

WebUI の設定パネルで入力するか、以下の構造を参考にしてください（`data/config/schedule_assistant_config.json`）：

```json
{
  "basic_settings": {
    "persona_id": "",
    "user_nickname": "",
    "user_ids": ["プラットフォームID:FriendMessage:ユーザーID"]
  },
  "schedule_reminder_settings": {
    "enable_schedule_reminder": false,
    "schedule_reminder_minutes": 10,
    "schedule_reminder_check_interval": 5
  },
  "habit_reminder_settings": {
    "enable_morning_report": true,
    "morning_report_time": "09:00",
    "enable_bath_reminder": true,
    "bath_time": "22:00",
    "enable_sleep_reminder": true,
    "sleep_time": "23:00",
    "enable_water_reminder": true,
    "water_interval": 90,
    "water_start_time": "09:30",
    "water_end_time": "21:30"
  },
  "calendar_sync_settings": {
    "enable_apple_calendar_sync": false,
    "apple_calendar_sync_interval": 30,
    "apple_calendar": { "username": "", "app_password": "", "calendar_id": "" },
    "webcal_urls": []
  },
  "external_services_settings": {
    "maton_api_key": "",
    "notion_db_ids": [],
    "weather_api_key": "",
    "weather_city": "北京"
  },
  "message_render_settings": {
    "markdown_enabled": true,
    "markdown_native_platforms": [],
    "qq_markdown_enabled": null
  },
  "prompt_settings": {
    "prompt_morning": "",
    "prompt_bath": "",
    "prompt_sleep": "",
    "prompt_water": "",
    "prompt_schedule": ""
  }
}
```

---

## 🛠️ LLM が呼び出せるツール

プラグインは 4 つの LLM ツールを登録しており、モデルが呼び出しタイミングを自動判断します。自然言語で要件を言うだけです：

```
ユーザー: 明日の朝 9 時にチーム定例を入れて
🤖 → create_schedule(title=チーム定例, datetime_str=明日の9時)
    予定「チーム定例」を作成しました。時間：08-17 09:00 ✅

ユーザー: 午後 3 時の会議を 4 時に変更して
🤖 → update_schedule(title_keyword=会議, new_datetime=午後4時)
    予定を変更しました：時間を午後 4 時に変更 ✅

ユーザー: 今週の予定を教えて
🤖 → list_schedules(days=7)
    📋 今後 7 日間の予定（全 3 件）：
    ━━━ 08-17 月 ━━━
      ⏰ 09:00 │ チーム定例
      ...

ユーザー: 明日の読書会を削除して
🤖 → delete_schedule(title_keyword=読書会)
    予定「読書会」を削除しました ✅
```

### create_schedule
新しい予定を作成します。

| パラメーター | 型 | 説明 |
|------|------|------|
| `title` | string | **必須**。予定のタイトル / 内容 |
| `datetime_str` | string | **必須**。自然言語の日時に対応（例：「明日の 9 時」「あさっての午後 3 時」「2024-01-15 14:30」） |
| `description` | string? | 任意のメモ |

### delete_schedule
予定を削除します。ID での完全一致またはタイトルキーワードでの部分一致に対応しています。

| パラメーター | 型 | 説明 |
|------|------|------|
| `schedule_id` | string? | 予定 ID（完全一致） |
| `title_keyword` | string? | タイトルのキーワード（部分一致、例：「会議」「定例」） |

### list_schedules
予定の一覧を表示します。

| パラメーター | 型 | 説明 |
|------|------|------|
| `days` | int? | 直近何日分の予定を表示するか。デフォルトは 7 日 |

### update_schedule
予定を変更します。タイトル、日時、メモを単独または組み合わせで更新できます。

| パラメーター | 型 | 説明 |
|------|------|------|
| `schedule_id` | string? | 予定 ID（完全一致） |
| `title_keyword` | string? | タイトルのキーワード（部分一致） |
| `new_title` | string? | 新しいタイトル |
| `new_datetime` | string? | 新しい日時。自然言語に対応 |
| `new_description` | string? | 新しいメモ |

---

## 📝 更新履歴

> 📋 **[更新履歴の全文を見る →](CHANGELOG.md)**

---

## ⭐ このプロジェクトを応援する

このプラグインが役に立ったら、Star ⭐ をいただけると嬉しいです。質問や提案は [Issue](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues) または [Pull Request](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/pulls) へどうぞ。

## 🙏 謝辞

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) オープンソースのチャットボットフレームワーク
- プラグインのロゴは Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279) から

---

## 📜 ライセンス

このプロジェクトは **MIT License** で公開されています。

---

## 👤 作者

[@OMSociety](https://github.com/OMSociety)
