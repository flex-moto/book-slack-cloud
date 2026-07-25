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

## （オプション）タイムズカーシェア 空き監視

ピックルボール監視と同じ作法で、**タイムズカーシェアの予約 空き状況を監視して Slack に通知する**機能も同梱しています（`timescar_monitor.py` / `.github/workflows/timescar.yml`）。使わない場合は設定不要です。

> **⚠️ ピックルボールとの違い＝ログイン必須 & reCAPTCHA**
> タイムズの空き状況ページはログインの内側にあり、ログインフォームは reCAPTCHA で保護されています。そのため**会員番号＋パスワードによる自動ログインは行いません**（規約・bot検知の観点でも不可）。代わりに、**手動ログイン済みのセッションCookieを再利用**します。Cookieは数時間〜数日で失効するため、失効時は「更新が必要」通知が飛びます。その都度、下記手順でCookieを取り直してください。

- 監視対象（既定・固定）: **利尻富士観光ホテル駐車場（`LM25`）** の **2026-08-10 / 08-11**、**8:00〜20:00**（時台 `08`〜`19`）の「空きあり(水色 = `.vacant`)」枠。車両ごと・時台の粒度で判定
- 頻度: **20分おき（毎時 5 / 25 / 45 分）**
- 仕組み: `timescar_monitor.py` がCookieで空き状況ページ（`/view/reserve/input.jsp?scd=<ステーション>&carBaseModelNm=&searchFlg=`）を開き、`table.time` 内の `td.timelinedot.vacant` を抽出。前回状態 `timescar_state.json` と比較して**空きが出た／満席に戻った**変化があれば Slack に投稿します
- ワークフロー: `.github/workflows/timescar.yml`（`workflow_dispatch` ＋保険の `schedule: 5,25,45 * * * *`）。定時実行は外部cron（cron-job.org）から20分おきに `workflow_dispatch` API を叩く想定です

> **📌 タイムテーブルは「現在時刻起点・12時間・15分刻み」の窓で、日付選択では動かず「次のタイムテーブルへ」で12時間ずつ進む作りです。** そのため対象日（例 2週間先の 08-10/11）に到達するには、実行のたびに窓を数十回送ります（現在日から離れるほど送り回数が増え、当日が近づくほど減ります）。上限は `TIMESCAR_MAX_PAGES`（既定60）。
>
> **⚠️ 負荷・規約の注意:** 20分おきに数十回のページ送り＝予約サーバへのアクセスが多く、bot的でありアカウント停止リスクもあります。対象日まで日数がある間は**頻度を落とす**（例: 1時間おき）ことを推奨します。特定の1日を待つだけなら、タイムズ本体の**「空き待ち設定」**機能（車両ごとに設定可）も有力な代替です。

### 設定（GitHub Secrets / Variables）

| 種類 | 名前 | 必須 | 説明 |
|---|---|---|---|
| Secret | `SLACK_BOT_TOKEN` | 必須 | 本の投稿と共用。`chat.postMessage` で投稿します |
| Secret | `TIMESCAR_COOKIE` | 必須 | 手動ログイン後のセッションCookie。`name=value; name2=value2` 形式 |
| Secret | `SLACK_CHANNEL_TIMESCAR` | 任意 | 投稿先チャンネルID。未設定なら `#reservation`（`C0BJ3ETJ1H7`） |
| Variable | `TIMESCAR_STATION` | 任意 | ステーションコード(`scd`)。未設定なら `LM25`（利尻富士観光ホテル駐車場） |
| Variable | `TIMESCAR_CARS` | 任意 | 監視対象の車両名の一部（カンマ区切り）。未指定なら全車両（例: `ハスラー,ルークス`） |
| Variable | `TIMESCAR_TARGET_DATES` | 任意 | 監視対象日 `YYYY-MM-DD` のカンマ区切り。未設定なら `2026-08-10,2026-08-11` |
| Variable | `TIMESCAR_TIMES` | 任意 | 監視する時台 `HH` のカンマ区切り。未設定なら `08`〜`19`（=8:00〜20:00） |
| Variable | `TIMESCAR_MAX_PAGES` | 任意 | タイムテーブル送りの上限回数（既定 `60`） |

### Cookieの取り出し方

1. ブラウザで [予約ページ](https://share.timescar.jp/view/reserve/input.jsp) にログイン（reCAPTCHAはここで通過）
2. DevTools → Application → Cookies → `share.timescar.jp` のCookie（`JSESSIONID` 等）を控える
3. `name=value; name2=value2` 形式にまとめて `TIMESCAR_COOKIE` Secret に登録

### 操作

| やりたいこと | 方法 |
|---|---|
| 今すぐ空き状況をチェック | Actions → timescar-slot-monitor → Run workflow（または `gh workflow run timescar.yml`） |
| 監視間隔を変更 | cron-job.org のジョブ、および `timescar.yml` の `schedule` を編集 |
| 状態をリセット | `timescar_state.json` を `[]` にしてコミット |
| ローカルで試す/内容確認 | `TIMESCAR_COOKIE=... TIMESCAR_DEBUG=1 python timescar_monitor.py` |

> **実DOM確認済み（2026-07、ログイン済みブラウザ）**: 空きセル=`td.timelinedot.vacant`（水色 `rgb(102,204,255)`）、満席=`.full`、予約不可=`.impossible`、メンテ=`.maintenance`。窓は12時間・15分刻みで「次のタイムテーブルへ」(`doSearchNextTimetableJs`)で12時間ずつ前進。ステーション `LM25` は夏季限定営業（6/1〜10月末）で車両はベーシック／ハスラー(1259165)・ルークス(1202623)の2台。判定は時台粒度（:45開始枠のみの空きは対象外）。既定値は上表のVariableで変更可。

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
