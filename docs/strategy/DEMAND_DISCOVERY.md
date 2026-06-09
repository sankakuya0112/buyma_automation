# 需要起点の商品発掘 (Demand Discovery) — Phase 2d

## 課題

「相場より安く・需要のある商品を仕入れる」が事業の大前提だが、
従来のパイプラインは **供給起点** だった:

```
baseblu セール品 (供給) → BUYMA 相場確認 → 利益が出れば出品
```

この構造では「たまたまセールに出ていた商品」しか扱えず、
需要側から商品を探しに行く経路が存在しなかった。

## 解決: 3 層の需要シグナル統合

### 1. 需要の定義 (何を需要とみなすか)

| シグナル | 取得元 | 意味 |
|---|---|---|
| BUYMA 出品数 (sample_count) | market fetch | **需要の実証**。多くのショッパーが扱う = 売れている |
| お気に入り数 (wish_total) | market fetch (検索カード) | 欲しい人の数の直接観測 |
| 仕入元消化率 (sellthrough) | baseblu sizes vs available_sizes | 現実にサイズが売れて消えている |
| 仕入元割引率 (discount_rate) | baseblu | 供給側の事情 (需要とは独立) |

**重要な発想転換**: 従来は「高競合 (n≥10) = 避けるべき」だったが、
高競合は **需要が実証されている** 最強のシグナル。問題は競合ではなく
「原価優位なしに参入すること」。原価優位があれば高競合こそ狙い目。

### 2. 価格決定での活用 (app/core/pricing.py)

- **price_leader 経路 (新設)**: 高競合でも市場最安値 -3% が breakeven 以上
  なら出品。最安値は検索ソートで露出が取れ、新規アカウントの信頼不足を
  価格で相殺できる。
- **market_aware_discounted (新設)**: 中競合で相場が target 未満でも、
  floor 利益を守れる限り相場-5% に下げて成約を取る
  (旧: max(target, 相場-5%) で「相場より高い売れない出品」を量産していた)。

### 3. 商品選別での活用 (app/core/opportunity.py)

```
opportunity_score = expected_profit_jpy × P(成約)
```

P(成約) は競合密度 (high 0.12 > medium 0.07 > low 0.04 > none 0.02) を
基礎に、価格優位・消化率・お気に入り数で補正。filter の出力 CSV は
この期待値順にソートされ、出品順 = 期待値順になる。

確率の絶対値は仮定。**相対ランキングに使うため単調性があれば機能する**。
成約実績が貯まったら sales_report と突き合わせて係数を較正する。

### 4. 仕入れ先探索での活用 (scripts/scout_demand.py)

需要 → 供給の逆引きスカウト:

```
┌─ モード 3 (Mac): --probe-from-csv latest
│    ブランド単位の BUYMA 需要を能動調査 → market_cache に蓄積
↓
┌─ モード 1 (どこでも): scout_demand.py
│    キャッシュをブランド集計 → 4 区分の需要インデックス
│      🎯 sweet_spot         需要あり×競合薄 → 最優先仕入れ
│      🔥 proven_high_demand 原価優位なら price_leader で勝負
│      🌱 exclusive          ロングテール (少量で反応観察)
│      ❓ unreliable         データ品質不足
↓
┌─ モード 2 (どこでも): --match-source latest
│    需要インデックス × セール CSV の交点 = 「需要が確認できている
│    ブランドの今買える在庫」リスト
↓
filter_baseblu_profitable.py → 出品 (opportunity_score 順)
```

## 推奨運用サイクル (週次)

1. (Mac) `python3 scripts/baseblu_sales_to_csv.py` — セール在庫更新
2. (Mac) `python3 scripts/scout_demand.py --probe-from-csv latest` — 全 vendor 需要調査
3. `python3 scripts/scout_demand.py --match-source latest` — 交点確認
4. (Mac) `python3 scripts/fetch_buyma_market_prices.py --csv latest` — 商品単位の相場
5. `python3 scripts/filter_baseblu_profitable.py --market <JSON>` — EV 順の出品リスト
6. (Mac) `python3 scripts/buyma_auto_listing.py --draft --limit N`

## 仕入先拡大との関係

demand_index の `proven_high_demand` ブランドは
**仕入先を増やすほど価値が上がる** (どこかに原価優位のある仕入先がある
可能性が高まる)。Italist 等の Source 追加 (PROCUREMENT_ROADMAP.md) 後は、
モード 2 の突き合わせを全 Source の在庫に対して行い、source_edge
(app/core/source_edge.py) で最安仕入先を選ぶ。

## 較正タスク (実績データが貯まったら)

- BASE_SALE_PROBABILITY: 成約実績 / 出品数 を競合密度別に集計して置換
- EDGE_SENSITIVITY: 価格優位と成約速度の相関で調整
- PRICE_LEADER_UNDERCUT (3%): 最安値登録後に追随されたら 5% へ
- お気に入り数セレクタ: Mac の --debug-html で実 HTML 確認 (初回必須)
