# Slack投稿の認証・部分成功からの復旧

## 2026-11-09 の失敗

- 書籍 run 42533012620: primaryは『すべての道はローマに通ず 下』を送信済み。secondaryは `files.getUploadURLExternal: invalid_auth`、WeChatは未実行。旧実装なので宛先別状態は残っていない。
- ニュース run 42533029080: `chat.postMessage: invalid_auth` で親投稿前に終了。
- 共通Secretは `SLACK_BOT_TOKEN_2`。この修正は有効なトークンを復元・発行しない。

## 認証の復旧

1. secondary側のSlackアプリのインストール状態とBotトークンの有効性を確認する。
2. 必要ならGitHub Actionsの `SLACK_BOT_TOKEN_2` を現在有効なBotトークンで更新する。チャット・コミット・ログにトークンを記載しない。
3. `auth.test` の成功だけでは送信権限やチャンネル参加は保証されない。想定ワークスペース、投稿先への参加、`chat:write`、書籍画像に必要な `files:write` を確認する。

## 今回の書籍投稿を再開する前に

旧runをそのまま再実行するとprimaryへ再送され得る。新しい保存方式は過去の成功を自動推定しない。

- primaryの実投稿を確認し、同じ本・紹介文を回収する。
- `data/book_post_state.json` にこの本と紹介文、日付、DATA_DIRからの相対パス、`history_before`（現行posted.logの行配列）、`targets: ["primary", "secondary", "wechat"]`、`channels`（primary/secondaryの各チャンネルID）、`sent: ["primary"]`、`complete: false` を設定する。`book` は `parse_note` と同じ全フィールドを含める。トークンを含めない。
- その状態を保存してから、修正後のコードで未送信先だけ再開する。SlackとWeChatの送信確認後に履歴が確定する。
- 今回分を送らない判断をする場合も、状態を推測して書き換えず、既存投稿と履歴を確認して対応を決める。

## 修正後の挙動

- 書籍は未送信Slack宛先すべての `auth.test` を本選択・AI生成前に確認する。
- 本と紹介文を保存し、宛先ごとの送信成功直後に状態を保存する。途中失敗時もActionsが状態をコミットする。
- 未完了の投稿を優先して再開する。宛先構成・チャンネルが変わっていたら停止する。同日完了済みなら再送しない。
- `posted.log` は全宛先の送信完了後に確定する。状態にはSecretを保存しない。
- ニュースも送信前に `auth.test` を行い、失敗コードをannotationと実行サマリーに記録する。dry-runは認証APIを呼ばない。

## 検証と限界

外部呼び出しをmockしたテストで、secondary失敗からの再開、WeChatだけの再開、認証失敗時の無送信、同日再送防止、宛先変更時の停止を確認する。

送信が成功した直後のプロセス強制終了・通信応答喪失、または状態コミット失敗では送信済みか判定できないことがある。この場合は自動再実行せず、実宛先と保存状態を照合する。厳密なexactly-once配信は保証しない。

適用後は各宛先の実投稿、Actionsの実行サマリー、`data/book_post_state.json`、`posted.log`、ニュースの親投稿・返信・`data/dlab_news/post_state.json` を照合する。

## 2026-11-10 の追加調査

- 書籍 run 42716832244: primaryには『「勉強法のベストセラー100冊」のポイントを1冊にまとめてみた。』を送信済み、secondaryで `invalid_auth`。旧runの再実行はprimaryへの重複送信になる。
- ニュース run 42716855759、クイズ run 42721659710も `SLACK_BOT_TOKEN_2` による `invalid_auth`。クイズにも送信前の認証チェックを追加した。
- Secretの最終更新は2026-07-08。有効なトークンの再発行・Secret更新は未実施。
- ピックルボール run 42672423763はジョブ未開始。その後の定期実行は成功しており、Slack secondary認証障害とは分けて扱う。
