# Mac の作業を AI に任せるセットアップガイド

## なぜ Mac での実行が必要なのか (前提)

この Claude Code Web 版 (クラウド) のサーバーは、セキュリティ上の理由で
baseblu.com / buyma.com にアクセスできません。そのため、

- **コードの開発・修正** → クラウドの Claude Code (今まで通り)
- **実際のスクレイピング・出品** → あなたの Mac

という分担になっています。「Mac での実行」自体は無くせませんが、
**Mac での操作を AI にやらせる**ことはできます。

---

## おすすめ: Mac に Claude Code を入れる

Claude Code は Web 版だけでなく、**Mac 上で動くデスクトップアプリ /
ターミナル版**があります。Mac 上の Claude Code は **Mac のネットワークを
使う**ので、baseblu / BUYMA にアクセスでき、この制限がありません。

つまり Mac 側の Claude Code に「週次パイプラインを実行して」と日本語で
頼むだけで、コマンド入力・エラー対応まで AI がやってくれます。

### セットアップ (初回のみ、5分)

1. **インストール** — 以下のどちらか:
   - デスクトップアプリ: https://claude.ai/download から
     Claude アプリをインストール (Claude Code 機能を含む)
   - ターミナル版: ターミナルを開いて
     ```bash
     npm install -g @anthropic-ai/claude-code
     ```
     (npm がない場合は https://nodejs.org から Node.js を先にインストール)

2. **プロジェクトフォルダで起動**:
   ```bash
   cd ~/buyma_automation
   claude
   ```

3. 初回はログイン (claude.ai のアカウント) を求められるので従う。

### 使い方 (毎回これだけ)

ターミナルで `cd ~/buyma_automation && claude` のあと、日本語で頼む:

```
git pull してから、週次パイプライン (scripts/run_weekly.py) を実行して。
エラーが出たら原因を診断して、直せるものは直して再実行して。
終わったら結果のサマリを教えて。
```

ポイント:
- このリポジトリには **CLAUDE.md / HANDOFF.md** が入っているので、
  Mac 側の Claude も自動でプロジェクトの文脈 (罠と対策・実行手順) を
  読み込みます。毎回説明し直す必要はありません。
- エラーが出ても、Claude がその場でログを読んで診断・修正できます。
  「ターミナル出力をコピーしてチャットに貼る」作業が不要になります。
- 出品テスト (`buyma_auto_listing.py --draft`) も同様に頼めます。
  ブラウザが立ち上がる様子も Mac 上でそのまま見えます。

### よく使う頼み方の例

| やりたいこと | Claude への頼み方 |
|---|---|
| 週次サイクル一式 | 「run_weekly.py を実行して。エラーは診断して」 |
| 出品テスト 1 件 | 「下書きモードで 1 件だけ出品テストして (--draft --limit 1 --hold)」 |
| 在庫チェック | 「check_inventory.py を dry-run で実行して、売切れ商品を教えて」 |
| 修正を取り込む | 「git pull origin claude/add-test-flag-HibqE を実行して」 |
| エラー調査 | 「さっきのエラーの原因を調べて修正して。修正内容は説明して」 |

### 役割分担 (推奨)

| 作業 | 担当 |
|---|---|
| コード開発・コミット・プッシュ | クラウドの Claude Code (Web 版、今まで通り) |
| スクレイピング・相場取得・出品実行 | **Mac の Claude Code** |
| 修正が必要なバグの発見 | Mac 側 Claude が診断 → 簡単なら Mac 側で修正、設計変更はクラウド側へ |

⚠️ 注意: Mac 側 Claude がコードを修正した場合、クラウド側と食い違わない
よう「修正したら commit して push して」と頼んでください (Mac から push
するには GitHub の Personal Access Token 設定が必要。設定していなければ
「修正内容をチャットに表示して」と頼み、クラウド側セッションに貼り付け)。

---

## 代替案 1: Claude Cowork

Claude デスクトップアプリの Cowork 機能でも Mac 上の作業を任せられますが、
このプロジェクトは「ターミナルでスクリプト実行 + git 操作」が中心のため、
**Claude Code の方が適しています**。Cowork はファイル整理やドキュメント
作成のような作業に向いています。

## 代替案 2: 完全自動化 (cron / launchd)

AI も介さず、Mac が自動で定期実行する方法。タイプ作業ゼロになりますが、
エラー時に自分で対処が必要なため、**Claude Code 運用に慣れてから**を推奨:

```bash
# 毎週月曜 9:00 に週次パイプラインを自動実行する例 (crontab -e で追記)
0 9 * * 1 cd ~/buyma_automation && /usr/bin/python3 scripts/run_weekly.py >> logs/weekly.log 2>&1
```

エラー通知は実装済みの notifier (Slack / メール) が拾います
(.env に SLACK_WEBHOOK_URL 等を設定した場合)。

---

## 手入力が必要な場合の保険: run_weekly.py

AI を使わない日でも、覚えるコマンドは 1 つだけです:

```bash
cd ~/buyma_automation && python3 scripts/run_weekly.py
```

これで「セール取得 → 利益フィルタ → 相場取得 → 相場連動フィルタ →
需要分析」まで全部、正しい順序で自動実行されます。失敗した工程は
コマンドとエラーが表示されるので、それを Claude に貼れば診断できます。
