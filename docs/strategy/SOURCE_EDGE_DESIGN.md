# Source Edge スコア設計ドラフト (Phase 2c+)

> **Status**: 設計ドラフト (実装は Italist 等 2 社目の Source 実装後)。
> 本書は PROCUREMENT_ROADMAP.md の「優先度 2: 仕入れ優位スコア」を詳細化したもの。

---

## 1. ゴール

複数仕入先 (Baseblu / Italist / Cettire / Mytheresa 等) が同じ製品を扱っているとき、

1. **最安仕入先を自動選択**
2. **2 番目との価格差 (edge) を計測**
3. edge が小さい (= 他バイヤーも同じ判断をしやすい) 商品を **warn** にする

ことで、価格競争に巻き込まれやすい商品を事前に避ける。BUYMA 内の市場相場 (median)
や Farfetch 外部ベンチマークと並ぶ「**仕入れ側の優位性**」評価軸を追加する。

---

## 2. 評価軸の整理 (既存ガードとの違い)

| 評価軸 | 何を見る | 出力 | 既存実装 |
|---|---|---|---|
| 偽相場ガード | BUYMA median が cost 同等 | fake_market / target 採用 | `decide_final_price` (Phase 2a) |
| 信頼度ガード | brand_match_confidence | no_market_data 扱い | `MarketStats.is_reliable` (Phase 2c) |
| 市場連動価格 | BUYMA median - 5% | market_aware / skip | `decide_final_price` (Phase 2a) |
| 外部ベンチマーク | Farfetch JP 最安値 | external_advantage / external_close / external_cheaper | `evaluate_external_benchmark` (Phase 2b) |
| **Source Edge (新)** | **2 仕入先以上の価格差** | **high_source_edge / low_source_edge / exclusive_source** | **未実装** |

source_edge は「仕入先側の競争力」を見る。他バイヤーも同じ仕入先を使う前提で、
2 番目に安い仕入先より十分安く仕入れられている商品ほど、価格を下げる余地がある。

---

## 3. 「同一製品」の同定方法

複数 source からの商品を「同じ」とみなすマッチング戦略。優先順位は **(1) → (3)**:

### (1) 製品 SKU 完全一致 [最優先]
- ブランドが SKU に独自フォーマットを持つ場合 (Gucci の `1BD075_2BLF_F0002` 等)
- 同一 SKU なら 99% 同一商品。Baseblu の `description_en` の `Sku:` と Italist
  ページの SKU 表示を比較。

### (2) ブランド + 型番抽出 [次優先]
- BURBERRY の `8085427_BLACK` は Baseblu でも Italist でも共通命名
- 正規表現: `[A-Z0-9]{6,}(?:_[A-Z0-9]+)?`

### (3) ブランド + タイトル類似度 [フォールバック]
- 編集距離 (Levenshtein) ベース、閾値 0.85
- 各 source のタイトルから「ブランド名 / 不要記号 / カラー名 / サイズ」を除いた
  正規化文字列で比較
- 例: "GIVENCHY G-Cube Mini Bag in Calf Leather" vs
      "GIVENCHY G-CUBE MINI BAG CALF LEATHER" → 0.92 マッチ

### マッチング結果の永続化
`data/source_index.json` に蓄積:
```json
{
  "<canonical_key>": {
    "brand": "GIVENCHY",
    "title_normalized": "g-cube mini bag",
    "sku_candidates": ["BB60JZB1NM_001", "BB60JZB1NM"],
    "matches": [
      {"source": "baseblu", "url": "...", "sale_price": 1200.0, "currency": "EUR", "matched_at": "..."},
      {"source": "italist", "url": "...", "sale_price": 1380.0, "currency": "USD", "matched_at": "..."}
    ]
  }
}
```

`canonical_key` は `make_product_key(brand, title_normalized, sku)` で生成 (既存
`app/core/external_benchmark.py:make_product_key` と同一規約)。

---

## 4. landed_cost の正規化 (DDP/DDU/通貨混在)

各 source の `sale_price` をそのまま比較するのは不正。**landed cost (関税・消費税・送料込みの円換算原価)** で比較する必要がある。

```
landed_cost_jpy(source, sale_price)
  = calculate_pricing(
        PricingParams(
            source_price=sale_price,
            currency=source.currency,
            category=...,
            landed_cost_basis=source.landed_cost_basis,  # DDP なら関税スキップ
        )
    ).total_cost_jpy
```

つまり既存 `BaseSource.get_pricing_params()` (Phase 2c で導入済み) を経由する
ことで、DDP/DDU と通貨を吸収できる。

---

## 5. SourceEdgeStats データモデル

```python
@dataclass
class SourceEdgeStats:
    canonical_key: str
    cheapest_source: str           # "baseblu"
    cheapest_landed_cost_jpy: int  # 64818
    second_cheapest_source: Optional[str]   # "italist" or None
    second_cheapest_landed_cost_jpy: Optional[int]  # 71200 or None
    edge_jpy: int                  # 6382 (= second - cheapest)
    edge_pct: float                # 9.85 ((second - cheapest) / cheapest * 100)
    n_sources: int                 # 2
    matched_at: str                # ISO8601
```

`cheapest_*` が現在の出品候補 (Baseblu) でない場合、出品判定は **「より安い source
に切り替えるか、SKIP するか」を呼出側で判断**する (= 自動切替はしない)。

---

## 6. 評価関数 (decide_final_price 統合案)

### 関数シグネチャ
```python
def evaluate_source_edge(
    edge: Optional[SourceEdgeStats],
    final_price_jpy: int,
    min_edge_jpy: int = 10000,
    min_edge_ratio: float = 0.05,
) -> tuple[str, str]:
    """
    Returns:
        (action, reason) — action は "pass" / "warn" / "skip"
    """
```

### 判定ルール

| 条件 | action | reason | 意図 |
|---|---|---|---|
| edge is None または n_sources <= 1 | `pass` | `exclusive_source` | 比較対象なしなら独占なので OK |
| 自分が cheapest_source でない | `skip` | `not_cheapest_source` | 他の source の方が安いので出品しない |
| edge_jpy < max(min_edge_jpy, final_price_jpy × min_edge_ratio) | `warn` | `low_source_edge` | 競合が同じ仕入先に集まりやすい |
| それ以外 | `pass` | `high_source_edge` | 仕入優位あり |

`min_edge_jpy = 10000` / `min_edge_ratio = 0.05` は初期値。実運用で調整。

### 既存 decide_final_price との接続
- 現状 `decide_final_price` は market / external benchmark を見て action を決める
- source_edge は「より上流」の判定: source_edge=skip なら decide_final_price を呼ぶ前にスキップ
- source_edge=warn は decision.reason に `|low_source_edge` を追記し、
  market_aware / external 側の warn と OR で取る

```
[CSV row]
  → resolve_source_edge(canonical_key) → SourceEdgeStats or None
  → if edge.action == "skip": continue (skip_reason="not_cheapest_source")
  → calculate_pricing (source.get_pricing_params)
  → decide_final_price (market 連動)
  → evaluate_external_benchmark (Farfetch)
  → 最終 action 決定
```

---

## 7. 段階的な実装マイルストーン

### Milestone 1: 単一仕入先 (Baseblu) のみで動く Stub
- `SourceEdgeStats` dataclass + `evaluate_source_edge` 関数を `app/core/source_edge.py` に追加
- `n_sources=1` で常に `("pass", "exclusive_source")` を返す
- `filter_baseblu_profitable.py` から呼び出し、出力 CSV に `source_edge_action` / `source_edge_reason` 列を追加
- ユニットテスト: 4 経路 (None / 1 source / 2 sources high edge / 2 sources low edge / not cheapest)
- **本セッションでも実装可能 (実データなしでも stub + テストは書ける)**

### Milestone 2: data/source_index.json の蓄積
- `scripts/build_source_index.py`: 各 source の最新 CSV を走査し canonical_key で集約
- マッチング (3) の Levenshtein 実装 (`difflib.SequenceMatcher` で十分)
- Italist 等の 2 社目が必要 → Phase 3-1 と並行

### Milestone 3: 自動切替 / 通知
- source_edge=skip の代わりに「より安い source に切り替えて再 fetch」する
  `swap_to_cheapest_source(canonical_key)` を実装
- ユーザー通知 (slack / email) で「この商品は Italist の方が安い」アラート

---

## 8. エッジケースと罠

| ケース | 対処 |
|---|---|
| 同じ source の中で variant ごとに価格差 | variant 単位で SKU が違うため自然に別商品扱い |
| Italist の在庫切れ表示 | `available=false` の row は match から除外 |
| 為替の日次変動 | landed_cost_jpy 計算時の exchange_rate を `matched_at` に記録 |
| カラー違い (黒のみ Italist にあり、白のみ Baseblu) | matches[].variant_color で分岐、別 canonical_key とする |
| Levenshtein 0.85 の閾値が緩すぎ | 同 brand / 同 product_type の制約を加算 |
| Italist の DDP は本当に DDP か | 商品ページで「Final price including duties」表記を確認、無ければ DDU 扱い |

---

## 9. テスト戦略

### ユニット (Milestone 1 で先行実装可)
- `evaluate_source_edge`:
  - None edge → `pass`, `exclusive_source`
  - n_sources=1 → `pass`, `exclusive_source`
  - n_sources=2 で edge >= threshold → `pass`, `high_source_edge`
  - n_sources=2 で edge < threshold → `warn`, `low_source_edge`
  - cheapest_source != current_source → `skip`, `not_cheapest_source`
  - threshold は max(min_edge_jpy, final × ratio) を使うこと
- `SourceEdgeStats.edge_pct` の計算精度

### 統合 (Milestone 2 以降)
- `data/source_index.json` のラウンドトリップ
- 同じ商品が 3 source 以上に出ているケース
- マッチング (1)(2)(3) の優先順位検証 (人手で fixture 作成)

---

## 10. オープン質問

1. **マッチング閾値** — Levenshtein 0.85 で十分か、ブランド固有のカスタム閾値が必要か
2. **edge の方向** — 2 番目より安い場合のみ評価する仕様だが、自分が 2 番目以下なら
   `not_cheapest_source` で skip する。これで OK か (e.g. 「とりあえず出して 2 番目の
   ブランドで売る」運用は捨てる前提)
3. **canonical_key の安定性** — title が変わると key が変わるが、SKU 一致が
   優先されるので大半は安定するはず。 source_index.json のリビルド頻度をどうするか
4. **Italist の product_type マッピング** — Baseblu の `BAGS` と Italist の `Bags` は
   揃えて持つか、source ごとに変換テーブルを持つか

---

## 11. 関連ファイル参照

- 現状: `app/core/external_benchmark.py` (構造の前例)
- Phase 2c 既存: `app/core/sources/{base,baseblu}.py`, `app/core/pricing.py:MarketStats`
- 統合先: `scripts/filter_baseblu_profitable.py`
- 蓄積データ: `data/source_index.json` (新設予定)
- ロードマップ: `docs/strategy/PROCUREMENT_ROADMAP.md` 優先度 2 を本書で詳細化
