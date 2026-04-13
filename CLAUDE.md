# CLAUDE.md - プロジェクト指示書

このファイルは Claude Code がセッション開始時に読み込む指示書です。
過去の経験から得た知見を記録し、同じミスを繰り返さないようにします。

---

## プロジェクト概要

BUYMA 自動出品ツール。baseblu.com からセール商品をスクレイピングし、
価格計算・翻訳を経て BUYMA に自動出品するパイプライン。

**メインスクリプト**: `scripts/run_pipeline.py`  
**ブランチ**: `claude/add-test-flag-HibqE`

---

## 実行環境について（重要）

### Claude Code サーバーでできること ✅
- コードの編集・作成
- DB 操作（SQLite）
- パッケージインストール（pip）
- ロジックのテスト（モックデータ使用）
- GitHub へのコミット・プッシュ

### Claude Code サーバーでできないこと ❌
- `baseblu.com` へのアクセス（ホワイトリスト外）
- `buyma.com` / `buyma.jp` へのアクセス（ホワイトリスト外）
- playwright のブラウザダウンロード（CDN がブロック）
- 一般的な外部 Web サイトへのスクレイピング

**理由**: Anthropic がセキュリティ上の理由で設けたネットワーク制限。
`GLOBAL_AGENT_HTTP_PROXY` に許可ドメインのホワイトリストが設定されている。
pypi.org・github.com 等の開発インフラのみ許可されている。

### 実際のスクレイピング・出品は Mac（ローカル）で実行する

```bash
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE
pip3 install -r requirements.txt
pip3 install playwright && playwright install chromium
python3 scripts/run_pipeline.py --test
```

---

## 失敗パターンと対策

### ❌ 失敗1: Claude Code サーバーから外部サイトにアクセスしようとした
- **発生**: `python3 scripts/run_pipeline.py --test` を実行 → baseblu.com に接続できず失敗
- **エラー**: `ProxyError: Tunnel connection failed: 403 Forbidden`
- **原因**: Claude Code サーバーのネットワーク制限
- **対策**: スクレイピング・出品はユーザーの Mac で実行するよう案内する。サーバーで実行しない

### ❌ 失敗2: playwright のブラウザダウンロードが失敗した
- **発生**: `playwright install chromium` → CDN から 403 エラー
- **原因**: playwright の CDN もホワイトリスト外
- **対策**: サーバー上にある既存の Chromium を使用する
  - パス: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`
  - `p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")`
  - `config.chromium_executable_path` で管理している

### ❌ 失敗3: Mac から GitHub へ push しようとしてパスワード認証を求められた
- **発生**: `git push` → GitHub ユーザー名・パスワードを求められた
- **原因**: GitHub はパスワード認証を廃止（Personal Access Token が必要）
- **対策**: Mac から push は不要。Claude Code サーバー側で push する。
  ユーザーには push を求めず、ファイル内容をチャットに貼り付けてもらう

### ❌ 失敗4: Mac に存在しないファイルを cp しようとした
- **発生**: `cp .env.example .env` → `No such file or directory`
- **原因**: `.env.example` はサーバー側にあるが Mac には同期されていなかった
- **対策**: Mac にないファイルを前提とした手順を案内しない。
  代わりに `cat > .env << 'EOF'` で直接作成する手順を案内する

### ❌ 失敗5: docs/ ファイルが Mac にあってサーバーにない状態を把握できなかった
- **発生**: `docs/phases/PHASE1_FOUNDATION.md` を読もうとしたが見つからなかった
- **原因**: ファイルが Mac ローカルにあり、GitHub に push されていなかった
- **対策**: ファイルが見つからない場合、すぐに「GitHub にプッシュするか内容を貼り付けてください」と案内する

### ❌ 失敗6: セキュリティ上問題のある情報をチャットで共有してもらった
- **発生**: BUYMA のログイン情報（メール・パスワード）をチャットに貼り付けてもらった
- **原因**: サーバー側に `.env` を設定する手段として誘導してしまった
- **対策**: 認証情報はユーザーの Mac 上で `.env` や `config.json` に設定するよう案内する。
  チャットへの貼り付けは避けてもらう（低リスクであっても）

---

## 成功パターン

### ✅ 成功1: モックデータを使ったパイプラインテスト
- `python3 scripts/run_all.py --test` → 正常動作
- モックデータ3件で価格計算・翻訳・CSV保存まで完走

### ✅ 成功2: SQLAlchemy DB の初期化・モデル定義
- `app/core/models.py` の8テーブル定義が正常動作
- `init_db()` で SQLite DB を初期化できることを確認済み

### ✅ 成功3: 全モジュールのインポート確認
- `app/` 以下の全モジュールが正常にインポートできることを確認済み

### ✅ 成功4: 既存 Chromium を使った Playwright 起動
- `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` で Playwright が動作することを確認
- `executable_path` を `config.chromium_executable_path` で管理

### ✅ 成功5: ファイル内容をチャットに貼り付けてもらう方法
- GitHub push ができない場合でも、ファイル内容をチャットに貼り付けてもらうことで対応できた

---

## 開発フロー

1. コードは Claude Code サーバーで編集・テスト（モックデータ）
2. コミット・プッシュは Claude Code サーバーから実行
3. 実際のスクレイピング・出品テストはユーザーが Mac で実行
4. エラーが出たらターミナルの出力をチャットに貼り付けてもらい、Claude Code で修正

---

## 認証情報の管理

- BUYMA のメール・パスワードは **Mac 上の `.env` または `config.json`** に設定
- `config.json` は `.gitignore` に追加済み（GitHub に漏れない）
- `.env` も `.gitignore` に追加済み
- チャットには絶対に貼り付けない
