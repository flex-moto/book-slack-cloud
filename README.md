# 📚 Book Slack Bot（クラウド版 / Mac不要）

処理は **GitHub Actions 上で実行**し、**毎朝8:00（日本時間）** に外部cron（cron-job.org）から起動します。あなたのMacの電源状態に関係なく動きます。

> **なぜ外部cron？** GitHub Actions の `schedule` cron は新規アカウント制限で発火しないため、定時トリガは外部cron（cron-job.org）から `workflow_dispatch` API を叩いて行っています。実際の処理（本選び〜Slack投稿）は従来どおり GitHub Actions 上で動きます。

- 対象データ: `data/Books`（書籍）＋ `data/02_読書メモ`（Kindleなど電子書籍のメモ）
- ランダムに1冊選び、Claude で紹介コメントを生成して Slack / WeChat に投稿
- 表紙: Books はローカルwebpを変換してアップロード / Kindleメモは Amazon の画像URLをそのまま使用
- 同じ本の連投を避けるため `posted.log` を毎回コミットして履歴管理（全部投稿し終えると自動リセット）

## 仕組み
- 定時トリガ … 外部cron（cron-job.org）が毎朝8:00 JST に `workflow_dispatch` API を叩く
- `.github/workflows/daily.yml` … `workflow_dispatch`（手動 / 外部cron からのトリガ用）で起動する GitHub Actions ワークフロー
- `post_book.py` … 本選び〜投稿の本体
- APIキー等は GitHub Secrets（`ANTHROPIC_API_KEY` / `SLACK_BOT_TOKEN` / `SLACK_CHANNEL`）に保存。コードには含めない

## WeChat通知

WeChat の個人チャットへ公式APIで直接投稿する仕組みはないため、まずは WeChat 内で受け取れる通知サービスに送ります。対応プロバイダは `WxPusher` と `ServerChan` です。

### WxPusher を使う場合（推奨）

GitHub リポジトリの Settings → Secrets and variables → Actions で次を設定します。

| 種類 | 名前 | 値 |
|---|---|---|
| Variable | `NOTIFY_TARGETS` | `wechat`（Slackにも送るなら `slack,wechat`） |
| Variable | `WECHAT_PROVIDER` | `wxpusher` |
| Secret | `WXPUSHER_APP_TOKEN` | WxPusher の appToken |
| Secret | `WXPUSHER_UIDS` | 送信先UID。複数ならカンマ区切り |
| Secret | `WXPUSHER_TOPIC_IDS` | topicId。UIDで送るなら未設定でOK |

`WXPUSHER_UIDS` と `WXPUSHER_TOPIC_IDS` はどちらか一方が必要です。

### ServerChan を使う場合

| 種類 | 名前 | 値 |
|---|---|---|
| Variable | `NOTIFY_TARGETS` | `wechat`（Slackにも送るなら `slack,wechat`） |
| Variable | `WECHAT_PROVIDER` | `serverchan` |
| Secret | `SERVERCHAN_SENDKEY` | ServerChan の SendKey |

将来的に特定の友人との個人チャット欄へ投稿したい場合は、`post_book.py` の `post_to_wechat()` に新しい provider を追加すると差し替えられます。ただしその方式は WeChat Desktop の自動操作など非公式ルートになりやすく、常時ログイン端末とアカウント制限リスクの管理が必要です。

## 本を追加したら（手動更新）
Obsidianで本を増やした後、ローカルで次を実行すると GitHub に反映されます:
```sh
zsh ~/book-slack-cloud/sync-data.sh
```

## 操作
| やりたいこと | 方法 |
|---|---|
| 今すぐテスト投稿 | GitHubリポジトリ → Actions → daily-book-post → Run workflow（または `gh workflow run daily.yml`） |
| 実行結果を見る | Actions のログ、または `gh run list` / `gh run view` |
| 投稿時刻を変更 | cron-job.org のジョブのスケジュールを編集（現状 毎朝8:00 JST = 23:00 UTC） |
| モデルを変更 | リポジトリの Settings → Variables に `ANTHROPIC_MODEL`（例 `claude-haiku-4-5`）を追加 |
| WeChatだけに投稿 | Settings → Variables に `NOTIFY_TARGETS=wechat` を追加 |
| SlackとWeChatに投稿 | Settings → Variables に `NOTIFY_TARGETS=slack,wechat` を追加 |
| 投稿履歴をリセット | `posted.log` を空にしてコミット |

## 注意
- 起動は外部cron（cron-job.org）に依存します。cron-job.org 側で使うGitHubトークン（Fine-grained PAT / `Actions: read & write`）の**有効期限が切れると停止**するので、その際は再発行してジョブの `Authorization` ヘッダを差し替えてください。
- 投稿時刻は外部cron・GitHub Actionsの負荷により数分ずれることがあります（毎朝の投稿なので実用上問題なし）。
- パブリックリポジトリの無料Actions枠は実質無制限、プライベートでも毎日1回なら無料枠（月2,000分）に十分収まります。
