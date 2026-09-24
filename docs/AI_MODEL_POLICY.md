# AI モデル使い分けポリシー (app/ai/)

最終更新: 2026-09-11

このプロジェクトで Claude API を「何に・どのモデルで・いくらまで」使うかの唯一の決め事です。
コード上の実体は `app/ai/router.py` (割り当て表) と `app/ai/client.py` (キャッシュ・台帳・予算) です。

---

## 1. 原則 (トークンを節約するための 5 つの約束)

| # | 原則 | 実装 |
|---|---|---|
| 1 | **決定論ファースト**: 計算で決まることに AI を使わない | 利益計算 / 相場フィルタ / 期待値ソートは従来どおり Python だけで行い、AI は `action=list` の上位 N 件 (既定 30) しか見ない |
| 2 | **量の仕事は最安モデル、判断の仕事だけ上位モデル** | 出品文・カテゴリ = Haiku 4.5 / 審査・診断 = Sonnet 5 / 週次レビュー = Fable 5.1 (週 1 回、集計値のみ) |
| 3 | **同じ入力に二度払わない** | `data/ai_cache.sqlite` に応答を保存。再実行・やり直しは 0 円 |
| 4 | **予算で自動停止** | `data/ai_usage.jsonl` に全リクエストを記録し、直近 7 日の合計が `AI_WEEKLY_BUDGET_JPY` (既定 ¥500) を超えたら AI を止めて辞書翻訳へ退避 |
| 5 | **鍵が無くても止まらない** | `ANTHROPIC_API_KEY` 未設定・通信失敗・拒否応答はすべて「AI なし」として従来ロジックで続行 (テスト・CI もこの経路) |

さらに 1 リクエストに複数商品をまとめ (出品文 8 件 / カテゴリ 20 件 / 審査 20 件)、
system prompt には prompt cache のブレークポイントを置き、出力は JSON スキーマ固定で短くしています。
カテゴリは「番号で答える」形式なので出力は 1 商品あたり数十トークンです。

---

## 2. 割り当て表

| タスク | 何をするか | 階層 | モデル (既定) | effort | 1 回に | 頻度 |
|---|---|---|---|---|---|---|
| `listing_copy` | 英語商品情報 → 日本語タイトル / 説明文 / 検索語 / 系統色 | cheap | `claude-haiku-4-5` | - | 8 商品 | 週 1 回 × 上位 30 件 |
| `category` | 辞書で決まらなかった商品の BUYMA 3 階層カテゴリ (番号回答) | cheap | `claude-haiku-4-5` | - | 20 商品 | 同上 (未決分のみ) |
| `judge` | 候補の list / hold / skip 判定・リスク・優先度 | standard | `claude-sonnet-5` | medium | 20 商品 | 週 1 回 |
| `diagnose` | Mac 実走ログの原因診断・対処手順 | standard | `claude-sonnet-5` | medium | 1 ログ | 失敗時のみ |
| `weekly_review` | 集計値から来週の一手を決める | premium | `claude-fable-5-1` | high | 1 回 | 週 1 回まで |

`python3 scripts/ai_cost_report.py --policy` で現在の割り当てを表示できます。

### なぜこの割り当てか
- 出品文・カテゴリは **件数が多く、間違えても後処理 (アクセント除去 / 幅トリム / 第 2 階層検証) で守れる** → 最安の Haiku。
- 審査は **規約リスクの見落としが痛い** が週 1 回 × 20〜30 件 → Sonnet で十分、Opus 以上は不要。
- 週次レビューは **1 回の判断が 1 週間の行動を決める** → 最上位の Fable。ただし生データは渡さず集計値だけなので数十円。

---

## 3. 費用の目安 (週 1 回、上位 30 件を補強した場合)

| タスク | 入力 tok | 出力 tok | 単価 (in/out $/Mtok) | 概算 |
|---|---|---|---|---|
| listing_copy | ≈ 20,000 | ≈ 13,000 | 1 / 5 | ≈ $0.09 |
| category (未決 10 件) | ≈ 3,000 | ≈ 300 | 1 / 5 | ≈ $0.005 |
| judge | ≈ 7,000 | ≈ 3,000 | 2 / 10 | ≈ $0.05 |
| weekly_review | ≈ 3,000 | ≈ 2,000 | 10 / 50 | ≈ $0.13 |
| **合計** | | | | **≈ $0.27 ≈ ¥45 / 週** |

2 回目以降はキャッシュ命中分が 0 円になるため、やり直しは実質無料です。
`python3 scripts/ai_enrich_candidates.py --dry-run` で送信前に概算を表示できます。
実績は `python3 scripts/ai_cost_report.py` (直近 7 日) で確認します。

---

## 4. 変更方法 (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...        # Mac の .env にだけ書く (チャットに貼らない)
AI_WEEKLY_BUDGET_JPY=500            # 週間上限 (超えたら自動で AI オフ)
AI_MODEL_CHEAP=claude-haiku-4-5     # 階層ごとのモデル
AI_MODEL_STANDARD=claude-sonnet-5
AI_MODEL_PREMIUM=claude-fable-5-1
AI_TASK_JUDGE_TIER=cheap            # タスク単位で階層を下げる例 (審査も Haiku に)
AI_DISABLED=1                       # 一時的に AI を全停止
```

Fable 5.1 が使えないアカウントの場合は `AI_MODEL_PREMIUM=claude-opus-5` にしてください。
Fable は安全分類器で応答を拒否することがあるため、コード側で server-side fallback
(`fallbacks="default"`) を有効にしています。拒否されても同じリクエスト内で別モデルが続きを返します。

---

## 5. 使い方 (Mac)

```bash
cd ~/buyma_automation
pip3 install -r requirements.txt            # anthropic が追加されている

# 取得 → 利益計算 → 相場 → AI 補強 (下書きは作らない)
python3 scripts/run_autopilot.py

# さらに上位 3 件を BUYMA に下書き保存 (公開は管理画面で人が押す)
python3 scripts/run_autopilot.py --skip-scrape --skip-market --draft 3

# 週末: Fable による週次レビュー
python3 scripts/run_autopilot.py --skip-scrape --skip-market --no-ai --weekly-review

# 失敗したら
python3 scripts/ai_diagnose.py --log /path/to/log --context "何をしていたか"
```

`--test` を付けるとモックデータで通し確認できます (ネット・API キー不要)。

---

## 6. できないこと / 制約

| 制約 | 理由 | 回避策 |
|---|---|---|
| Claude Code のクラウドから実行できない | baseblu.com / buyma.com がネットワーク許可外 | Mac で実行 (docs/MAC_AI_SETUP.md) |
| 自動で「公開」まではしない | 未検証コードの誤公開・アカウント評価リスク | 下書き = ツール、公開 = 人間 (docs/strategy/FIRST_SALE_SPRINT.md) |
| AI の判定 (hold / skip) は最終決定ではない | 規約判断は責任を伴う | skip は出品対象から外す、hold は `--include-review` で人が確認して出す |
| Fable 5.1 は 30 日データ保持が必要 | Anthropic の提供条件 | ZDR 契約の組織は `AI_MODEL_PREMIUM=claude-opus-5` |
| 画像の生成・加工はしない | 費用対効果が未検証 | 売上発生後に検討 (PHASE3) |

---

## 7. 次の節約レバー (必要になったら)

1. **Message Batches API** (50% 引き): 出品文生成を夜間バッチにする。`app/ai/client.py` に `submit_batch` を足すだけで済む構造。
2. **effort を下げる**: `judge` を `low` にしても品質が落ちなければ `router.py` の `effort` を変更。
3. **キャッシュ TTL**: 週次実行の間隔が長いため prompt cache は 5 分 TTL のまま (再送のたびに書き直す)。連続実行時のみ効く。
4. **上位 N を絞る**: `--ai-limit 10` で費用は約 1/3。
