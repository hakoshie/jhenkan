# JHenkan

Windows上のどのアプリでも `Ctrl+J` でローマ字・かなを自然な漢字かな交じり文へ変換する、軽量な常駐ツールです。無料枠のあるGoogle GeminiとOpenAI APIを切り替えられます。

## インストール

`install.cmd` をダブルクリックしてください。初回だけ必要な部品をインストールし、そのまま常駐アプリを起動します。PowerShellやGit Bashを普段開く必要はありません。

コマンドから行う場合だけ、次も利用できます。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

初回の設定画面でプロバイダーを選び、そのAPIキーを入力してください。初期設定はGeminiの `gemini-3.6-flash`、OpenAI側は `gpt-5.6-luna` です。APIキーは設定JSONではなくWindows資格情報マネージャーにプロバイダー別で保存されます。「Windowsへのサインイン時に起動」は初期状態でオンです。

- Gemini APIキー: <https://aistudio.google.com/api-keys>
- OpenAI APIキー: <https://platform.openai.com/api-keys>

自動起動を切った状態で後から起動するときは、`JHenkanを起動.cmd` をダブルクリックします。

## 使い方

- 選択せず `Ctrl+J`: 前回の変換後からカーソル手前へ入力した文字列を変換
- 直前の変換結果を選択して `Ctrl+Shift+J`: 元の入力から別候補へ再変換（同じウィンドウ内の直前の結果のみ。追加のAPI呼び出しが発生します）
- 変換したい文字を選択して `Ctrl+J`: 選択部分を直接再変換
- タスクトレイの `J` アイコン: 一時停止、設定、終了

例: `ashita 10ji ni toukyou eki de aimashou` → `明日10時に東京駅で会いましょう`

通常入力と `Ctrl+V` で貼り付けた文字列は裏側の未確定バッファにも記録され、`Backspace` はその末尾を削除します。マウスをクリックしたとき、カーソルを移動したとき、別ウィンドウへ切り替えたときには、誤った場所を置換しないようバッファを破棄します。変換中は入力先を変えないでください。入力先へ戻れない場合は誤貼り付けせず、変換結果だけをクリップボードへ残します。

## 制限

これはWindowsの正式なTSF入力メソッドではなく、グローバルホットキー、キー入力監視、クリップボードを使うIME風ツールです。そのため、管理者権限で動くアプリ、パスワード欄、一部の端末・ゲームでは動かない場合があります。変換成功後、クリップボードには変換結果が残ります。

## APIとプライバシー

変換対象の文字列だけを、設定中のGeminiまたはOpenAI APIへ送信します。モデルとプロバイダーは設定画面で変更できます。APIキーはWindows資格情報マネージャーに保存され、リポジトリ内のファイルには保存されません。通常の診断ログには入力本文やAPIキーを記録しません。設定で診断ログモードを有効にした場合だけ、変換前・変換後の本文を `jhenkan.log` に記録します。調査後は無効にしてください。

## 謝辞

このツールは、[Sumibi](https://github.com/kiyoka/Sumibi) の「ローマ字を入力して `Ctrl+J` で日本語へ変換する」という操作体験に着想を得ています。JHenkanは任意のWindowsアプリで動作させるための独立したPython実装で、Sumibiのソースコードは含みません。SumibiはGNU GPL v3で公開されています。

JHenkanは[MIT License](LICENSE)で公開しています。

## 自動起動を解除する

設定でチェックを外すか、次を実行します。

```powershell
.\uninstall-startup.ps1
```
