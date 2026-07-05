# 📚 Book Slack Bot（クラウド版 / Mac不要）

GitHub Actions で **毎朝8:00（日本時間）に自動実行**。あなたのMacの電源状態に関係なく動きます。

- 対象データ: `data/Books`（書籍）＋ `data/02_読書メモ`（Kindleなど電子書籍のメモ）
- ランダムに1冊選び、Claude で紹介コメントを生成して Slack に投稿
- 表紙: Books はローカルwebpを変換してアップロード / Kindleメモは Amazon の画像URLをそのまま使用
- 同じ本の連投を避けるため `posted.log` を毎回コミットして履歴管理（全部投稿し終えると自動リセット）

## 仕組み
- `.github/workflows/daily.yml` … cron `0 23 * * *`（=日本時間8:00）＋手動実行ボタン
- `post_book.py` … 本選び〜投稿の本体
- APIキー等は GitHub Secrets（`ANTHROPIC_API_KEY` / `SLACK_BOT_TOKEN` / `SLACK_CHANNEL`）に保存。コードには含めない

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
| 投稿時刻を変更 | `daily.yml` の cron を編集（UTC。日本時間−9時間） |
| モデルを変更 | リポジトリの Settings → Variables に `ANTHROPIC_MODEL`（例 `claude-haiku-4-5`）を追加 |
| 投稿履歴をリセット | `posted.log` を空にしてコミット |

## 注意
- GitHub Actions のスケジュールは負荷により数分ずれることがあります（毎朝の投稿なので実用上問題なし）。
- パブリックリポジトリの無料Actions枠は実質無制限、プライベートでも毎日1回なら無料枠（月2,000分）に十分収まります。
