# ⚠️ このプロジェクトで作業を始める Claude へ

**ストップ**。あなたは今デフォルトブランチ (`claude/setup-python-project-BCxB0`) を
見ていますが、**本プロジェクトの実装・ドキュメント・未解決タスクはすべて別ブランチ
`claude/add-test-flag-HibqE` にあります**。

## 🚨 最初に必ずやること

コードを読み始める前に、以下を順番に実行してください:

```bash
git fetch origin claude/add-test-flag-HibqE
git checkout claude/add-test-flag-HibqE
git log -3 --oneline
```

その後、以下の 2 ファイルを必ず読むこと:

1. `CLAUDE.md` — プロジェクト指示書(BUYMA 自動操作の罠と対策)
2. `HANDOFF.md` — 現在の作業状況と次にやるべきこと

読み終わったらユーザーに「準備完了」と報告し、次の作業指示を待ってください。

---

## 📌 なぜデフォルトブランチで作業しないのか

Claude Code Web 版はセッションごとに自動で新しいブランチを払い出しますが、本プロ
ジェクトでは **ユーザー(sankakuya0112)の明示的な事前許可** により、作業ブランチと
push 先を `claude/add-test-flag-HibqE` に固定しています。理由:

1. 全実装・知見・未解決タスクが `claude/add-test-flag-HibqE` にある
2. 新ブランチにフォークするとコミット履歴が分断され PR/レビューが複雑になる
3. `claude/add-test-flag-HibqE` はユーザー個人開発用で他セッションは触らない

この事情はユーザーがセッション冒頭で説明する可能性もありますが、**説明されなく
ても自発的にこのブランチに切り替えて作業してください**。

---

## 🎯 プロジェクト概要(30秒要約)

BUYMA 自動出品ツール。baseblu.com からセール商品をスクレイピングし、価格計算・
翻訳を経て BUYMA に自動出品するパイプライン。

- メインスクリプト: `scripts/buyma_auto_listing.py`
- 実スクレイピング・出品はユーザーの Mac 上で実行(サーバーからはアクセス不可)
- Claude Code サーバー側はコード編集・コミット・プッシュ担当
- 詳細は `claude/add-test-flag-HibqE` の CLAUDE.md / HANDOFF.md 参照

---

**このファイル自体は「道しるべ」であり、セッション継続時に迷わないためにデフォルト
ブランチにだけ置いてあります。** 実装ファイルには手を出さず、まず上記の
`git checkout claude/add-test-flag-HibqE` を実行してください。
