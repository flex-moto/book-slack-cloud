#!/bin/zsh
# Obsidian の最新の本データ（Books と 02_読書メモ）を GitHub に反映する手動更新コマンド。
# 使い方: 本を追加した後に  zsh ~/book-slack-cloud/sync-data.sh  を実行するだけ。
set -e

VAULT="/Users/motomuratakuya/Desktop/Obsidian Vault"
REPO="$(cd "$(dirname "$0")" && pwd)"

echo "[sync] 最新データをコピー中..."
rm -rf "$REPO/data/Books" "$REPO/data/02_読書メモ"
cp -R "$VAULT/Books" "$REPO/data/Books"
cp -R "$VAULT/02_読書メモ" "$REPO/data/02_読書メモ"

cd "$REPO"
if [[ -z "$(git status --porcelain data)" ]]; then
  echo "[sync] 変更なし。更新するデータはありませんでした。"
  exit 0
fi

git add data
git commit -m "chore: update book data ($(date '+%Y-%m-%d'))"
git push
echo "[sync] 完了。GitHub に最新の本データを反映しました。"
