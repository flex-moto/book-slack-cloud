# DラボAIニュースのクラウド収集

## 運用

既存のcron-job.orgが平日08:00 JSTに `daily-dlab-news.yml` を起動します。同じGitHub Actions実行内で、Dラボから記事取得 → 要約 → ストック保存 → Slack投稿 → 投稿履歴保存 → 稼働状況チェックを行います。日々の運用にMac・Codexの起動は不要です。

収集にはDラボ公式MCP（https://mcp.daigovideolab.jp/mcp）を使用し、要約には既存のAnthropic APIキーを使います。モデルは `DLAB_SUMMARY_MODEL` 変数で指定でき、既定は `claude-haiku-4-5` です。新しく取り込む記事だけを要約し、記事ごとに最大1,800出力トークンに制限します。Anthropic APIの従量料金が発生します。

以前のMac上のCodex定期収集は、クラウド動作確認後に停止します。

## 初回認証・更新

DラボのDaiGoプランとD-Lab Proプランが有効なアカウントで、一度接続を許可します。

```sh
python3 scripts/dlab-cloud-login.py --repo flex-moto/book-slack-cloud
```

表示されたURLでDラボへログインすると、認証トークンが `gh` 経由でGitHub Actions Secret `DLAB_MCP_TOKEN` に直接保存されます。トークンは画面・ファイル・Gitへ出力しません。実行環境にはPythonと、リポジトリのSecretsを設定できるログイン済みGitHub CLIが必要です。

DラボのOAuth認証は約90日で期限切れになります。公開された認証メタデータはrefresh token方式をサポートしていないため、期限切れ時は同じ手順で再認証します。日常の実行環境としてMacは不要ですが、認証更新はブラウザ操作が必要です。期限は `DLAB_MCP_TOKEN_EXPIRES_AT` 変数に保存し、14日前からActionsに警告します。

## 記事収集

- AIチャンネルの最新20件を取得し、公開14日以内の未登録記事を候補にします。日次まとめページは個別記事との重複を避けて除外します。
- 記事タイトルでDラボ本文を検索し、対象URLに一致する検索結果だけを要約モデルへ渡します。
- 記事内の指示は無視し、確認できた情報だけを250文字以内の概要・600文字以内の詳細にまとめます。
- 記事URL・公開日・収集日はコード側で固定します。出典URLが取得内容に見つからなければDラボ記事URLを使います。
- 最新20件を超える記事の完全な収集は保証しません。前回確認日まで届かない場合はActionsに網羅範囲の警告を出します。
- 認証・取得・要約・検証のいずれかに失敗した場合、ストックや確認日時を更新せず失敗として報告します。取得に成功し新規候補がなければ確認日時だけ更新します。
- 収集失敗時も、既存の新鮮な未投稿ストックがあれば投稿を試みます。ただし実行全体は失敗扱いにし、収集障害を隠しません。
- Gitへの保存には既存のfetch・rebase・push再試行を使用します。収集ストックの保存が失敗した場合、新規のSlack投稿は開始しません。

## 投稿ルール・監視

- 未投稿で公開から14日以内の記事だけを、公開日が新しい順に選びます。同日公開の候補間はランダムです。
- URL単位の履歴を保持し、同じ日本時間の日付に二重投稿しません。ストック切れでも履歴をリセットしません。
- 親投稿が成功し返信が失敗した場合は、次回にその返信だけを再試行します。
- 最終収集確認から3日以上で警告、7日超で失敗にします。
- 未投稿記事が0件で当日の投稿記録もなければ失敗。当日投稿済みなら次回分の枯渇警告とします。残数1〜2件も補充警告を出します。
- ActionsのSummaryには最終収集確認、未投稿記事数、本日の親投稿記録、未送信返信を表示します。
- Slack API成功直後の強制終了や履歴のGit保存失敗では、厳密な一度だけの送信は保証しません。失敗した実行を確認してから再実行してください。

## 検証・保守

```sh
python3 -m unittest discover -s tests -p 'test_dlab_news*.py' -v
python3 dlab_news_stock.py
python3 dlab_news_health.py
```

GitHubで収集から保存まで検証し、Slackには送らない場合:

```sh
gh workflow run daily-dlab-news.yml --repo flex-moto/book-slack-cloud -f collect_only=true
```

収集・要約を実行してもGitへの保存とSlack送信をしない場合:

```sh
gh workflow run daily-dlab-news.yml --repo flex-moto/book-slack-cloud -f dry_run=true
```

`dry_run` でも外部APIへの取得・要約は実行します。外部通信をせず保存済み記事の表示だけを確認するには `python3 dlab_news_post.py --dry-run` を使います。

旧 `news_bank.xlsx` と `dlab_news_posted.log` は使用しません。現在のストックは `data/dlab_news/news_stock.json`、投稿履歴は `data/dlab_news/post_state.json` です。
