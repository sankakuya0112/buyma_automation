# ChatGPT 再レビュー依頼パッケージ (Round 2)

**作成日**: 2026-04-26  
**前回レビュー**: 2026-04-23 → 指摘 16 項目を `REVIEW_RESPONSE.md` で対応  
**目的**: Tier 1 (価格計算訂正) + Tier 2 (低競合戦略) の妥当性評価

---

## ChatGPT への指示文 (このまま貼り付け可)

```
あなたは越境 EU → BUYMA 転売事業を客観的に評価する経営アドバイザーです。
以下のシステムは前回レビュー (2026-04-23) で指摘した 7 項目の修正を行いました。
修正内容と実測結果をレビューし、以下の観点で評価してください:

1. **修正の妥当性**: Tier 1 (為替・手数料・floor) の数値は実態に即しているか。
   過剰修正・過少修正があれば指摘してください。
2. **低競合戦略の論理**: 「BUYMA で他店出品が少ない商品を target 価格で
   独占的に出品する」戦略は、新規アカウント (信頼プレミアムなし) にとって
   合理的か。リスクと対処は妥当か。
3. **SKIP 9 件の判断**: high_competition (6 件) と below_breakeven (3 件) の
   分類は妥当か。THE LATEST 系の偽相場混入疑いをどう処理すべきか。
4. **月次想定利益 ¥890k の現実性**: 出品可 19 件のうち、何件が「実際に
   売れる」と予測されますか? 評価稼ぎ期 (累計販売 < 20 件) の現実的な
   月次成約数は何件と見積もれますか?
5. **次に着手すべき優先順位**: A) 連続出品テスト / B) fetch ロジック精度改善 /
   C) VAT 還付・送料の実値検証 / D) 画像権利・自前撮影 のうち、
   どれを最優先にすべきか。

対応済の項目は再評価不要。新たな懸念点 / 見落としているリスク / 数字の
妥当性で気になる箇所のみ指摘してください。
```

---

## 添付資料 1: 修正実装の要約

### Tier 1: 価格計算の数値訂正

| 項目 | 旧 | 新 | 根拠 |
|---|---|---|---|
| 為替 EUR/JPY | 163 | **186** | ECB 2026-04-23 参考値 |
| BUYMA 成約手数料 | 5.8% | **7.7%** | 一般出品者の実値 |
| 決済手数料 | 3.0% | **0%** | 購入者負担のため計上不要 |
| 振込手数料 | 0 | **¥330/件** | 220-385 円の中央値 (BUYMA 入金時差し引き) |
| floor (CLOTHING/FOOTWEAR) | ¥5k or 5% | **¥10k or 8%** | 返品・サイズ相談リスク |
| floor (BAGS) | ¥5k or 5% | **¥8k or 6%** | 検品手間 |
| floor (ACCESSORIES/他) | ¥5k or 5% | 維持 | 軽量・低リスク |

実装: `app/core/pricing.py` (定数・`_floor_profit`・`_solve_breakeven_price` 改修)

### Tier 2: 低競合戦略への pivot

`decide_final_price()` を競合密度ベースに書き換え:

```
sample_count == 0      → none    : target 採用 (no_market_data)
sample_count == 1      → low     : target 採用 (low_competition、独占強気)
sample_count 2-9       → medium  : target vs (中央値 -5%) の高いほう、
                                    breakeven 割れなら SKIP (below_breakeven)
sample_count >= 10     → high    : SKIP (high_competition、価格競争不利)
median < cost * 50%    → none    : target 採用 (fake_market、偽相場ガード)
```

戦略ドキュメント: `docs/strategy/LOW_COMPETITION_STRATEGY.md`

---

## 添付資料 2: 実測結果サマリ (2026-04-26)

### 件数フロー

```
全 70 件 → 在庫なし 42, 利益不足 1, 出品可 19, SKIP 9
                                              ├ high_competition 6
                                              └ below_breakeven 3
```

### 主要数値の修正前後比較

| 指標 | 修正前 | 修正後 |
|---|---|---|
| 出品可件数 | 20 | **19** |
| 原価中央値 | ¥109k | **¥157k** (+44%) |
| 売価中央値 | ¥189k | **¥212k** (+12%) |
| 利益中央値 | ¥34k | **¥39k** (+15%) |
| 利益最大 | ¥131k | **¥149k** (BRUNELLO BAG) |
| 最低利益率 | 8.6% | **25.0%** (全件 floor 防衛) |
| 期待利益合計 | ¥833k | **¥890k** |

### 出品可 Top 5 (期待利益順)

| # | 商品 | 競合 | reason | 売価 | 利益 |
|---|---|---|---|---|---|
| 1 | BRUNELLO CUCINELLI Shoulder Bag | none | no_market_data | ¥808,700 | ¥149,314 |
| 2 | BENEDETTA BRUZZICHES Mame Bag (large) | none | no_market_data | ¥465,200 | ¥85,907 |
| 3 | BENEDETTA BRUZZICHES Mame Bag (small) | none | no_market_data | ¥399,600 | ¥73,767 |
| 4 | ALAÏA Lavallière Blouse | none | no_market_data | ¥302,700 | ¥55,899 |
| 5 | BRUNELLO CUCINELLI Sandals | none | no_market_data | ¥300,200 | ¥55,466 |

### SKIP 9 件の詳細

| # | vendor | reason | n | median | breakeven | cost |
|---|---|---|---|---|---|---|
| 1 | TOM FORD | high_competition | 12 | ¥193k | ¥208k | ¥176k |
| 2 | GIVENCHY | high_competition | **28** | ¥115k | ¥174k | ¥147k |
| 3 | FIORUCCI | below_breakeven | 3 | ¥56k | ¥109k | ¥93k |
| 4 | FRANCESCO MURANO | high_competition | 10 | ¥39k | ¥63k | ¥48k |
| 5 | COURRÈGES | below_breakeven | 4 | ¥26k | ¥59k | ¥44k |
| 6 | JACOB COHEN | high_competition | 10 | ¥28k | ¥54k | ¥40k |
| 7 | DI STAVNITSER | below_breakeven | 9 | ¥27k | ¥46k | ¥38k |
| 8 | THE LATEST (1) | high_competition | 11 | ¥26k | ¥42k | ¥29k |
| 9 | THE LATEST (2) | high_competition | 11 | ¥30k | ¥40k | ¥27k |

---

## 添付資料 3: 自社考察 (再レビュー前の自己評価)

### 妥当と判断している点

1. **GIVENCHY n=28 の SKIP**: メジャーブランドで赤字確定。新規アカウントが
   参入しても勝てない好例。
2. **AFTERCOAT 4 件出品可 (全 fake_market or none)**: 当初の戦略仮説どおり
   低競合コアブランドとして機能。
3. **floor カテゴリ別化**: 全 19 件が利益率 25% 以上を確保。返品リスクの高い
   CLOTHING/FOOTWEAR で実質防衛できる水準。

### 懸念点

1. **THE LATEST 系 2 件**: median ¥26-30k vs cost ¥27-29k。偽相場ガード閾値
   (cost × 50%) を超えるため fake_market 扱いにならず high_competition で
   SKIP。実際は BUYMA で全く同等品が ¥26k で売られているとは考えにくく、
   default 商品リスト混入の疑い。
2. **competition_level=low (n=1) の運用が未検証**: 今回データには n=1 が
   ゼロだったため判断ロジックが実測では未稼働。
3. **need 検証 (needs validation)**: 「競合ゼロ = 独占チャンス」と仮定したが、
   「競合ゼロ = 需要ゼロ」の可能性も同等に存在。少量出品の反応観察が必要。
4. **BRUNELLO CUCINELLI BAG ¥808k**: 単価が極端に高い。1 件売れれば月次目標
   到達するが、新規アカウントで売れる確率は低い。アカウント評価育成期に
   含めるべきか、安定期まで待つべきか判断が必要。

### 質問事項

1. THE LATEST 系の偽相場ガード閾値を 0.5 → 0.7 に引き上げるべきか?
   副作用 (薄利競合の本物中央値も fake_market 扱い) はどう対処すべきか?
2. 月次想定利益 ¥890k は「累計 100 件売れたら」の合計。月次成約数は何件で
   見積もるべきか? 評価稼ぎ期 (< 20 件) の現実的な数字は?
3. 連続出品テストで何件・何日間で「需要シグナル」が観察可能か?
   (BUYMA はお気に入り数・閲覧数を出品者に表示するため)
4. BRUNELLO CUCINELLI BAG ¥808k は「累計評価 0 件」の状態で公開しても
   購入される可能性があるか? それとも累計評価 10 件以上まで非公開・
   下書き保留すべきか?

---

## 添付資料 4: ファイル参照ガイド

ChatGPT に追加情報が必要な場合に貼るべきファイル:

| 質問内容 | 貼るファイル |
|---|---|
| 価格計算ロジック詳細 | `app/core/pricing.py` (約 600 行) |
| 戦略の運用ポリシー | `docs/strategy/LOW_COMPETITION_STRATEGY.md` |
| 前回レビュー指摘への対応 | `docs/review/REVIEW_RESPONSE.md` |
| 詳細な実測結果 | `docs/review/RESULTS_2026-04-26.md` |
| 元の事業仕様 | `docs/review/BUSINESS_VIABILITY_SPEC.md` |

---

## 利用方法

1. このファイル全体を ChatGPT のプロンプトとして貼り付け
2. 必要に応じて添付資料 4 のファイルを追加で貼り付け
3. ChatGPT の評価を `docs/review/REVIEW_2_RESPONSE.md` に保存
4. 指摘事項を Phase 2a Tier 3 として実装する判断材料に使用

---

## チェックリスト (送信前)

- [x] Tier 1 修正が `app/core/pricing.py` に反映済
- [x] Tier 2 修正が `app/core/pricing.py` + `filter_baseblu_profitable.py` に反映済
- [x] 実測結果 (2026-04-26) をサマリ済
- [x] SKIP 9 件の reason 別内訳を整理済
- [x] 自社考察を明記 (ChatGPT に「自分で気づいてない指摘」を求めるため)
- [x] 質問事項を 4 つに絞り込み済
