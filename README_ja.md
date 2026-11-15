<p align="center"><a href="README.md">中文</a> · <a href="README_en.md">English</a> · <a href="README_ru.md">Русский</a> · <strong>日本語</strong></p>

<div align="center">

<h1><img src="https://raw.githubusercontent.com/OMSociety/astrbot_plugin_schedule_assistant/main/logo.png" width="192" alt="Schedule Assistant Logo"><br>Schedule Assistant スケジュールアシスタント</h1>

**あなたの頼れるスケジュール管理役** —— 朝のブリーフィング · 習慣リマインダー · LLM スケジュール管理 · Apple カレンダー双方向同期 · Notion ToDo 同期

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-orange.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/stargazers)
[![Issues](https://img.shields.io/github/issues/OMSociety/astrbot_plugin_schedule_assistant)](https://github.com/OMSociety/astrbot_plugin_schedule_assistant/issues)

[機能](#機能) • [動作の仕組み](#動作の仕組み) • [クイックスタート](#クイックスタート) • [設定項目](#設定項目) • [LLM ツール](#llm-ツール) • [変更履歴](CHANGELOG.md)

</div>

> 本プロジェクトは AI が執筆 · ロゴは Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

---

## 機能

| 機能 | 説明 |
|------|------|
| **フレームワーク任せの配信** | リマインダー本文は AstrBot のメイン Agent が対象セッションの人格と履歴で生成し、`send_message_to_user` で送信します。プレーンテキストのみ |
| **毎日の朝ブリーフィング** | 天気 + 今後 24 時間の予定（ローカルと Apple）+ Notion ToDo を 1 通にまとめます |
| **習慣リマインダー** | 入浴・就寝・水分補給の時刻を設定できます |
| **予定リマインダー** | 予定開始の N 分前に、予定のメモを踏まえて通知します |
| **LLM スケジュール管理** | 追加・削除・一覧・変更を自然言語で操作できます |
| **Apple カレンダー双方向同期** | iCloud CalDAV の読み書き、重複排除と差分更新に対応 |
| **Notion ToDo 同期** | 朝のブリーフィングに期限カウント（残り N 日 / 今日締切 / 期限超過）を表示 |

---

## 動作の仕組み

リマインダーは AstrBot の主動 Agent 機構で配信されます。プラグインは時刻に合わせてデータとタスク説明を組み立て、フレームワークの `active job` に渡すだけです。フレームワークが対象セッションのメイン Agent を起動し、そのセッションの人格と履歴で本文を生成して `send_message_to_user` で送信します。

したがって口調はボットに設定した人格に従います。プラグイン側に別の人設設定はありません。

配信はすべてプレーンテキストです。配信に失敗した回はそのまま失われ、自動再試行や重複した追い送りは行いません。

### 朝のブリーフィング

設定した時刻に毎朝配信します。

- 現在の天気と予報
- 配信時刻から 24 時間以内のローカル予定と Apple 予定（統合・重複排除）
- Notion ToDo と期限カウント
- 終日予定はブリーフィング当日のみ集計

内蔵プロンプトは本文を 120 字以内に抑えます。カスタムプロンプトを入力すると、執筆要件と出力要件の両方を置き換えます。

### 習慣リマインダー

| 習慣 | 既定時刻 | 説明 |
|------|----------|------|
| 入浴 | 22:00 | 変更可能 |
| 就寝 | 23:00 | 変更可能 |
| 水分補給 | 90 分ごと | 09:30–21:30 の範囲 |
| 予定リマインダー | N 分前 | 既定では無効 |

### Apple iCloud カレンダー双方向同期

**読み取り（Apple → ローカル）**
- 定期的に iCloud の予定をローカルへ取り込みます
- 追加・変更・削除を Apple カレンダー基準で同期します

**書き込み（ローカル → Apple）**
- ボット経由で作成した予定を指定カレンダーへ書き込みます
- イベント UID を保存し、以後の照合と重複排除に使います

**必要な項目**
- `username` — Apple ID のメールアドレス
- `app_password` — [appleid.apple.com](https://appleid.apple.com) で発行する **App 用パスワード**（ログインパスワードではありません）
- `calendar_id` — 対象カレンダーの UUID。空なら先頭。ログの `名前 → UUID` 一覧か `.../calendars/<UUID>/` から取得できます
- `caldav_host` — CalDAV ホスト。既定は `caldav.icloud.com`。中国本土のアカウントは `caldav.icloud.com.cn`、それでも通らない場合は `pXX-caldav.icloud.com.cn` のような分割ホストを指定します

### Notion ToDo 同期

Notion の ToDo は朝のブリーフィングに期限カウント付きで表示されます。Maton Gateway 経由で接続します。

---

## クイックスタート

### 1. インストール

AstrBot WebUI → プラグインマーケット → `schedule_assistant` を検索

> **ヒント：** 依存関係は `requirements.txt`（`aiohttp`、`python-dateutil`）にあります。AstrBot はプラグイン読み込み時に不足分を確認して導入します。

### 2. セッション一覧を設定

通知を受け取るセッション（私信またはグループ）で `/sid` を送り、返ってきた UMO を控えます。次に WebUI のプラグイン設定 → **基本設定** → `user_umos` に 1 行ずつ入力します。

```
qq:FriendMessage:123456789
qq:GroupMessage:987654321
```

`platform:message_type:session`（UMO 形式）。形式が不正な項目は起動時に 1 回警告してスキップします。

グループは独立したユーザーとして扱われ、メンバーは 1 つの予定リストを共有します。おはよう・入浴・就寝・水分の配信もグループへ送られるため、メンバーが承知していることを確認してください。

### 3. 任意：Notion

1. [Maton](https://www.maton.ai/) で Notion を接続（OAuth2）し、**Maton API Key** を発行
2. **外部サービス** の `maton_api_key` に入力し、`notion_db_ids` にデータベースを指定（例：`Tasks:xxx`、`Reading:yyy`）

> **注意：** Notion のデータは公式 API ではなく第三者ゲートウェイ `gateway.maton.ai` を経由します。`maton_api_key` は同ゲートウェイへ送信され、指定したデータベースのタイトル・ステータス・期限などを読み取ります。

---

## 設定項目

### 基本設定

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `user_umos` | list | `[]` | 配信先セッションの UMO 一覧。1 行に 1 件の `platform:message_type:session` |

### 予定リマインダー

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `enable_schedule_reminder` | bool | `false` | 予定リマインダーの有効化 |
| `schedule_reminder_minutes` | int | `10` | 何分前に通知するか。終日予定は対象外 |

### 習慣リマインダー

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `enable_morning_report` | bool | `true` | 朝ブリーフィングの有効化 |
| `morning_report_time` | string | `09:00` | 配信時刻（HH:MM） |
| `enable_bath_reminder` | bool | `true` | 入浴リマインダー |
| `bath_time` | string | `22:00` | 入浴時刻 |
| `enable_sleep_reminder` | bool | `true` | 就寝リマインダー |
| `sleep_time` | string | `23:00` | 就寝時刻 |
| `enable_water_reminder` | bool | `true` | 水分補給リマインダー |
| `water_interval` | int | `90` | 間隔（分） |
| `water_start_time` | string | `09:30` | 開始時刻 |
| `water_end_time` | string | `21:30` | 終了時刻 |

### カレンダー同期

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `enable_apple_calendar_sync` | bool | `false` | 双方向同期の有効化 |
| `apple_calendar_sync_interval` | int | `30` | 同期間隔（分） |
| `apple_calendar.username` | string | - | Apple ID のメールアドレス |
| `apple_calendar.app_password` | string | - | App 用パスワード |
| `apple_calendar.caldav_host` | string | - | CalDAV ホスト |
| `apple_calendar.calendar_id` | string | - | 対象カレンダーの UUID |
| `webcal_urls` | list | `[]` | WebCal 購読 URL |

> **WebCal の安全性：** `webcal_urls` は公開 `https://` のみ受け付けます（`webcal://` は変換）。SSRF 対策として `localhost`、プライベート網、クラウドメタデータ（`169.254.169.254`）は拒否します。

### 外部サービス

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `maton_api_key` | string | `""` | Maton API Key（Notion に必要） |
| `notion_db_ids` | list | `[]` | `Task:xxx`、`Reading:yyy` 形式 |
| `weather_api_key` | string | `""` | Seniverse API Key |
| `weather_city` | string | `Beijing` | 天気の都市 |

### リマインダーのプロンプト

| 項目 | 型 | 既定値 | 説明 |
|------|----|--------|------|
| `prompt_morning` | string | `""` | 朝のプロンプト。プレースホルダー：`{date} {weekday} {weather_current} {weather_forecast} {agenda} {notion_todos}` |
| `prompt_bath` | string | `""` | 入浴。`{current_time} {default_time}` |
| `prompt_sleep` | string | `""` | 就寝。`{current_time} {default_time}` |
| `prompt_water` | string | `""` | 水分補給。`{current_time}` |
| `prompt_schedule` | string | `""` | 予定。`{item_title} {time_label} {ahead_label} {item_context}` |

> 空欄なら内蔵プロンプト（データ部・執筆要件・出力要件）を使います。入力した場合はすべて置き換わり、プラグインは追加の制約を付けません。配信はプレーンテキストなので、「本文のみ、システムに触れない」などの指示は自分で書いてください。

### 設定例

```json
{
  "basic_settings": {
    "user_umos": ["qq:FriendMessage:123456789", "qq:GroupMessage:987654321"]
  },
  "schedule_reminder_settings": {
    "enable_schedule_reminder": false,
    "schedule_reminder_minutes": 10
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
    "apple_calendar": {
      "username": "",
      "app_password": "",
      "caldav_host": "",
      "calendar_id": ""
    },
    "webcal_urls": []
  },
  "external_services_settings": {
    "maton_api_key": "",
    "notion_db_ids": [],
    "weather_api_key": "",
    "weather_city": "Beijing"
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

## LLM ツール

プラグインは 4 つの LLM ツールを登録します。呼び出しはモデルが判断するので、自然言語で依頼するだけです。

> **時刻の書き方：** ISO / 数値（`2024-01-15 14:30`、`2024-01-15 09:00-11:00`、`2024-01-16`）または中国語の言い方（明天9点 = 明日 9 時、明天9点到11点 = 明日 9〜11 時、明天全天 = 明日終日）。日付だけなら終日です。

```
ユーザー: 明日9時に会議を追加して
-> create_schedule(title=会議, datetime_str=明天9点)
   予定「会議」を作成しました。時刻：08-17 09:00 ✅

ユーザー: 今週の予定は
-> list_schedules(days=7)
   📋 今後7日間の予定（3 件）：

   ━━━ 08-17 月 ━━━
     ⏰ 09:00 │ 会議

ユーザー: 明日の読書会を削除して
-> delete_schedule(title_keyword=読書会)
   予定「読書会」を削除しました ✅
```

### create_schedule

| 引数 | 型 | 説明 |
|------|----|------|
| `title` | string | **必須**、予定のタイトル |
| `datetime_str` | string | **必須**、ISO / 数値または自然言語。日付だけなら終日 |
| `end_datetime_str` | string? | 範囲の終了時刻（例 `11点`）。省略時は単一時刻（Apple は 1 時間） |
| `description` | string? | メモ |

### delete_schedule

| 引数 | 型 | 説明 |
|------|----|------|
| `schedule_id` | string? | 予定 ID（完全一致） |
| `title_keyword` | string? | タイトル語（部分一致） |

### list_schedules

| 引数 | 型 | 説明 |
|------|----|------|
| `days` | int? | 何日先までか。既定 7 |

### update_schedule

| 引数 | 型 | 説明 |
|------|----|------|
| `schedule_id` | string? | 予定 ID（完全一致） |
| `title_keyword` | string? | タイトル語（部分一致） |
| `new_title` | string? | 新しいタイトル |
| `new_datetime` | string? | 新しい時刻。書き方は `datetime_str` と同じ |
| `new_end_datetime` | string? | 新しい終了時刻。`new_datetime` と併用 |
| `new_description` | string? | 新しいメモ |

## 変更履歴

> **[変更履歴を見る →](CHANGELOG.md)**

## サポート

役に立ったら Star をお願いします。Issue と Pull Request も歓迎です。

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- ロゴは Pixiv Pid: [130776279](https://www.pixiv.net/artworks/130776279)

## ライセンス

MIT License。

[@OMSociety](https://github.com/OMSociety)
