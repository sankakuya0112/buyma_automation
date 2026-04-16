# BUYMA自動出品システム — マスタープラン

## このドキュメントについて
実装指示書の全体像。各Phaseの詳細は `docs/phases/` にある個別指示書を参照。

## システム思想
「大量出品ツール」ではなく「半自動運営会社のオペレーションシステム」。
- 自動化: スクレイピング〜出品〜在庫監視〜カート投入まで
- 人間判断: 最終購入確定・高額例外判断・問い合わせ最終送信
- 禁止事項: 自動で注文確定まで進めない / ログなしの実装禁止

## 8つのコンポーネント
| # | 名前 | 役割 | Phase |
|---|------|------|-------|
| 1 | Governor | 出品禁止判定・重複チェック・監査ログ | 1 |
| 2 | Scout | 複数仕入れ先スクレイピング | 1, 5 |
| 3 | Ranker | 競合分析・利益判定・レーン分け | 3 |
| 4 | Listing Factory | 出品データ生成・BUYMA登録 | 1 |
| 5 | Guard | 在庫監視・価格変動監視・自動停止 | 2 |
| 6 | Order Desk | 注文検知・再採算確認・カート投入 | 4 |
| 7 | Support | 問い合わせ下書き生成 | 6 |
| 8 | Reporter | 売上・利益分析レポート | 6 |

## 実装順序
- **Phase 1**: 基盤整理（DB導入・ディレクトリ再構成・既存コード移植）
- **Phase 2**: 事故防止（Guard — 在庫監視・自動停止）
- **Phase 3**: 利益最大化（Ranker — 競合調査・レーン分け）
- **Phase 4**: 注文オペレーション（Order Desk — カート投入・人間確認）
- **Phase 5**: 仕入れ先拡張（Scout — YOOX, SSENSE等）
- **Phase 6**: 運営支援（Support + Reporter）

## DB構造（SQLite）
`app/core/models.py` にスキーマ定義。主要テーブル:
- source_products / ranked_products / listings
- listing_events / inventory_checks
- orders / cart_queue / order_actions
- messages / evidence_files / daily_metrics

## ディレクトリ構成
```
buyma_automation/
├── app/
│   ├── core/          ← 共通基盤（config, logger, db, models）
│   ├── governors/     ← Governor
│   ├── scouts/        ← Scout（サイト別スクレイパー）
│   ├── rankers/       ← Ranker
│   ├── listing/       ← Listing Factory
│   ├── guard/         ← Guard
│   ├── orders/        ← Order Desk
│   ├── support/       ← Support
│   ├── reporting/     ← Reporter
│   └── utils/         ← 共通ユーティリティ
├── scripts/           ← 実行エントリポイント
├── data/              ← JSON設定
├── outputs/           ← CSV出力
├── logs/              ← 実行ログ
├── tests/             ← テスト
└── CLAUDE.md          ← Claude Code用指示書
```
