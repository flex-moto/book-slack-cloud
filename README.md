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

## （オプション）ピックルボール予約 空き監視

本の投稿とは別に、**PICKLEBALL ONE GINZA SHIMBASHI のコート予約の空き枠を監視して Slack に通知する**機能も同梱しています。使わない場合は設定不要で、本の投稿には影響しません。

- 監視対象: 平日（月〜金）の **19:00 / 20:00 開始**の枠、直近2週間以内
- 仕組み: `monitor.py` が予約サイト（[reserva.be](https://reserva.be/pboneginza/reserve)）をヘッドレスブラウザ（Playwright）で読み取り、前回状態 `pickleball_state.json` と比較して**空きが出た／満席に戻った**変化があれば Slack に投稿します
- ワークフロー: `.github/workflows/pickleball.yml`（`workflow_dispatch`）。定時実行は外部cron（cron-job.org）から **15分ごと**に `workflow_dispatch` API を叩く想定です
- 状態管理: 変化検知後に `pickleball_state.json` を毎回コミットして前回状態を保持します

### 設定（GitHub Secrets）

| 種類 | 名前 | 必須 | 説明 |
|---|---|---|---|
| Secret | `SLACK_BOT_TOKEN` | 必須 | 本の投稿と共用。`chat.postMessage` で投稿します |
| Secret | `SLACK_CHANNEL_PB` | 任意 | 投稿先チャンネルID。未設定なら `#reservation`（`C0BJ3ETJ1H7`） |

> Slack App を投稿先チャンネル（例: `#reservation`）に招待しておく必要があります（未招待だと `not_in_channel` で投稿失敗）。

### 操作

| やりたいこと | 方法 |
|---|---|
| 今すぐ空き状況をチェック | Actions → pickleball-slot-monitor → Run workflow（または `gh workflow run pickleball.yml`） |
| 監視間隔を変更 | cron-job.org のジョブのスケジュールを編集（現状 15分ごと） |
| 状態をリセット | `pickleball_state.json` を `[]` にしてコミット |
| ローカルで試す | `pip install playwright && playwright install chromium` の後 `python monitor.py` |

## 今日のクイズ（dlab記事ベースのSlackクイズ）

dlab（daigovideolab.jp）のブログ記事30本から作成した120問（4択×30記事）のクイズバンクを元に、**毎朝1記事分（4問）**を rechain-inc の `#今日のクイズ` へ自動投稿します。

- `data/quiz/quiz_bank.xlsx` … クイズ本体（記事タイトル・URL・4択問題・正解）。`scripts/build_quiz_bank.py` を実行すると作り直せます。中身を直接Excelで編集してもOK（`quiz_post.py` はExcelを直接読みます）
- `quiz_post.py` … 未投稿の記事を1つ選び、問題本文→スレッド返信で正解、の順にSlackへ投稿。全30記事を投稿し終えたら自動的に最初から繰り返します
- `quiz_posted.log` … 投稿済みの記事インデックスを記録（`post_book.py` の `posted.log` と同じ仕組み）
- `.github/workflows/daily-quiz.yml` … `workflow_dispatch` で起動するワークフロー。外部cron（cron-job.org）から平日朝8:35 JST（=前日23:35 UTC、`35 23 * * 0-4`）に叩く想定

### 設定（GitHub Secrets）

| 種類 | 名前 | 説明 |
|---|---|---|
| Secret | `SLACK_BOT_TOKEN_2` | 本の投稿(rechain-inc向け)と共用のボットトークン |
| Secret | `SLACK_CHANNEL_QUIZ` | `#今日のクイズ` チャンネルのID |

> Slack App（book-slack-cloudが使っているBot）を `#今日のクイズ` に招待しておく必要があります（未招待だと `not_in_channel` で投稿失敗）。

### 操作

| やりたいこと | 方法 |
|---|---|
| 今すぐテスト投稿 | GitHubリポジトリ → Actions → daily-quiz-post → Run workflow（または `gh workflow run daily-quiz.yml`） |
| クイズを追加・修正 | `data/quiz/quiz_bank.xlsx` を直接編集、または `scripts/build_quiz_bank.py` を編集して再生成 |
| 投稿履歴をリセット | `quiz_posted.log` を空にしてコミット |
| 投稿時刻を変更 | cron-job.org のジョブのスケジュールを編集 |

## 今日のクイズ（LINE版）

同じ `data/quiz/quiz_bank.xlsx` を使い、LINE公式アカウントの友だち全員へ**Broadcast配信**します。LINEにはSlackのスレッド機能がないため、**問題**と**正解・解説**を2回の別実行に分けて送ります（間隔は運用側のcronで調整。デフォルト想定は2時間後）。

- `line_quiz_post.py` … `QUIZ_PHASE`（`question` / `answer`）で動作を切り替える
  - `question` … 未投稿の記事を1つ選び、問題文（4問+心理学ボーナス1問）をBroadcast。選んだ記事番号を `line_quiz_state.json` に「回答待ち」として保存
  - `answer` … `line_quiz_state.json` に保存された記事の正解・解説をBroadcast。送信後 `line_quiz_posted.log` に記録し、state をクリア
  - 前回の回答待ちが残っている状態で `question` を実行すると、二重投稿を避けるため何もせずスキップします
- `line_quiz_posted.log` / `line_quiz_state.json` … 投稿履歴と「回答待ち」の状態管理（`quiz_posted.log` と同じ仕組み）
- `.github/workflows/daily-quiz-line.yml` … `workflow_dispatch`（`phase` 入力で `question`/`answer` を指定）で起動

### LINE Channel Access Tokenの取得手順

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン（LINEアカウントでOK）
2. 「新規プロバイダー作成」→ プロバイダー名を入力
3. そのプロバイダー内で「新規チャネル作成」→ **Messaging API** を選択し、チャネル名・業種などを入力して作成（これがLINE公式アカウントになります）
4. 作成したチャネルの「Messaging API設定」タブを開く
5. ページ下部「チャネルアクセストークン（長期）」で **発行** をクリック → 表示された文字列が `LINE_CHANNEL_ACCESS_TOKEN`
6. 同じ画面で **応答メッセージ・あいさつメッセージをオフ**にしておくと、Bot的な自動応答と競合しません
7. QRコードを友だち追加してテストできます（Broadcastは友だち登録している全員に届くので、テスト中は自分だけを友だちにしておくのがおすすめ）

### 設定（GitHub Secrets）

| 種類 | 名前 | 説明 |
|---|---|---|
| Secret | `LINE_CHANNEL_ACCESS_TOKEN` | 上記手順で発行した長期チャネルアクセストークン |

### 操作

| やりたいこと | 方法 |
|---|---|
| 今すぐ問題をテスト投稿 | Actions → daily-quiz-post-line → Run workflow → `phase: question`（または `gh workflow run daily-quiz-line.yml -f phase=question`） |
| 今すぐ正解をテスト投稿 | 同ワークフローを `phase: answer` で実行 |
| 定時実行を組む | cron-job.orgに2つのジョブを登録し、`workflow_dispatch` APIを叩く（`inputs: {"phase": "question"}` / `{"phase": "answer"}`）。2つ目は1つ目の2時間後に設定 |
| クイズを追加・修正 | Slack版と共通の `data/quiz/quiz_bank.xlsx` を編集 |
| 投稿履歴をリセット | `line_quiz_posted.log` を空にし、`line_quiz_state.json` を削除してコミット |

## dlab AI情報 毎日投稿（fyi_ai関連最新ニュース_情報）

dlab（daigovideolab.jp）のAIチャンネルから選んだ直近のAI関連ニュース記事15本を元に、**毎朝1本の概要**を Slack の `#fyi_ai関連最新ニュース_情報`（チャンネルID: `C05KPV4DSLS`）へ自動投稿します。

- `data/dlab_news/news_bank.xlsx` … 記事バンク（day_index・タイトル・URL・公開日・概要）。中身を直接Excelで編集してもOK（`dlab_news_post.py` はExcelを直接読みます）
- `dlab_news_post.py` … 未投稿の記事を1つ選びSlackへ投稿。全15記事を投稿し終えたら自動的に最初から繰り返します
- `dlab_news_posted.log` … 投稿済みの記事インデックスを記録（`quiz_posted.log` と同じ仕組み）
- `.github/workflows/daily-dlab-news.yml` … `workflow_dispatch` で起動するワークフロー。外部cron（cron-job.org）から毎朝8:00 JST（=前日23:00 UTC、`0 23 * * *`）に叩く想定

### 設定（GitHub Secrets）

| 種類 | 名前 | 説明 |
|---|---|---|
| Secret | `SLACK_BOT_TOKEN_2` | 本の投稿・クイズ投稿と共用のボットトークン |
| Secret | `SLACK_CHANNEL_DLAB_NEWS` | 任意。投稿先チャンネルID。未設定なら `C05KPV4DSLS`（`#fyi_ai関連最新ニュース_情報`） |

> Slack App（book-slack-cloudが使っているBot）を `#fyi_ai関連最新ニュース_情報` に招待しておく必要があります（未招待だと `not_in_channel` で投稿失敗）。

### 操作

| やりたいこと | 方法 |
|---|---|
| 今すぐテスト投稿 | GitHubリポジトリ → Actions → daily-dlab-news-post → Run workflow（または `gh workflow run daily-dlab-news.yml`） |
| 記事を追加・入れ替え | `data/dlab_news/news_bank.xlsx` を直接編集 |
| 投稿履歴をリセット | `dlab_news_posted.log` を空にしてコミット |
| 投稿時刻を変更 | cron-job.org のジョブのスケジュールを編集 |

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
