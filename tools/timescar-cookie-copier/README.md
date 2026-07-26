# Timescar Cookie Copier

タイムズカーのログインに使う2ドメインのCookieを、GitHub Actionsの
`TIMESCAR_COOKIE` と `TIMESCAR_COOKIE_TIMESCLUB` で使える
`name=value; name2=value2` 形式にコピーするローカルChrome拡張です。

## 安全設計

- アクセス対象は `https://share.timescar.jp/*` と `https://api.timesclub.jp/*` のみ
- ユーザーが拡張のボタンを押したときだけCookieを取得
- Cookieの外部送信、ファイル保存、拡張内保存をしない
- Cookie本文を拡張画面やコンソールへ表示しない
- Cookieの追加・変更・削除をしない

## インストール

1. Chromeで `chrome://extensions` を開く
2. 右上の「デベロッパー モード」を有効にする
3. 「パッケージ化されていない拡張機能を読み込む」を押す
4. この `timescar-cookie-copier` フォルダを選ぶ

## 使用方法

1. Chromeで `https://share.timescar.jp/` にログインし、「ログイン状態を保持」を有効にする
2. ツールバーの拡張機能メニューから「Timescar Cookie Copier」を開く
3. 「share.timescar.jp をコピー」を押し、GitHubの `TIMESCAR_COOKIE` Secretへ貼り付ける
4. もう一度拡張を開き、「api.timesclub.jp をコピー」を押す
5. GitHubの `TIMESCAR_COOKIE_TIMESCLUB` Secretへ貼り付ける

拡張を更新した場合は、`chrome://extensions` の「Timescar Cookie Copier」にある
再読み込みボタンを押してから使用してください。

コピーしたCookieはログイン情報そのものです。チャット、スクリーンショット、
ログ、通常ファイルへ貼り付けないでください。Cookie更新後に不要なら、
`chrome://extensions` から拡張を削除できます。
