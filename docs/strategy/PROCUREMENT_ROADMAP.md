# 仕入先拡大ロードマップ

Phase 2b 時点では Baseblu 単独。ChatGPT Round 2 レビューで指摘された通り、
**仕入れ優位を作るには複数仕入先の横断比較が不可欠**。本ドキュメントは
Phase 2c 以降で実装する候補仕入先の整理と、各サイトの注意事項をまとめる。

---

## DDP/DDU 別 仕入先一覧

### DDP (チェックアウト価格に関税・輸入税込み)

| サイト | 確度 | 備考 |
|---|---|---|
| Italist | 高 | イタリア系ブティック横断。日本向け表示は関税込みの説明あり |
| Tessabit | 高 | 多国 DDP 対応。価格安定 |
| Antonioli | 中 | ニッチ・前衛系ブランド。日本向け税込価格表示 |
| LUISAVIAROMA | 中 | 表示価格に関税・輸入税込み (要最新規約確認) |

### DDU (商品価格のみ。関税・輸入消費税は別途)

| サイト | 確度 | 備考 |
|---|---|---|
| Baseblu | 確 | 現行採用。Asia 向け送料 €50, €850 超で送料無料 |
| FRMODA | 中 | JPY 表示でも決済 EUR、関税は顧客負担と明記 |

### 不明 (要検証)

| サイト | 備考 |
|---|---|
| GIGLIO Outlet | DDP/DDU 国別の可能性。チェックアウトで確認必須 |
| SSENSE | 関税込み/別が地域・商品で変動 |
| CETTIRE | 返品時に送料・関税・税金が返金されない点に注意 |
| Farfetch | 主にベンチマーク用途。仕入れ先としてはコスト高 |

---

## BUYMA 規約準拠リスト

### 禁止仕入先 (出品資格停止リスク)

- **CtoC**: メルカリ / ラクマ / ヤフオク / eBay
- **大量輸入系**: AliExpress / Alibaba / Taobao
- **真贋不明**: 出所が確認できないアウトレットサイト
- **国内 EC** (一般): 国内転売は禁止 (一部例外あり、要確認)

### 注意が必要な仕入先

- 並行輸入のみ扱う非正規ブティック → 鑑定トラブルリスク
- セール率が異常に高いサイト (-80% 等) → 偽物の可能性

### 推奨仕入先

- 正規取扱店であることが確認できる
- 請求書 (invoice) が発行できる
- 商品が**本物保証付き**である
- 配送業者が DHL / FedEx / UPS のいずれか

---

## 各サイトの実装時注意事項

### Italist (Phase 2c で最初に追加候補)

| 項目 | 内容 |
|---|---|
| 認証 | 不要 (公開価格) |
| 通貨 | JPY 表示可能 |
| Anti-bot | 中程度 (Cloudflare あり) |
| 画像権利 | 商品画像の許諾要確認 |
| 検索 | API なし、HTML スクレイピング |
| レート制限 | 5-10 秒/req 推奨 |

### Tessabit

| 項目 | 内容 |
|---|---|
| 認証 | 不要 |
| 通貨 | EUR (要為替変換) |
| Anti-bot | 弱 |
| 画像権利 | 商品画像の許諾要確認 |
| 検索 | HTML スクレイピング、SPA 部分あり |

### Antonioli

| 項目 | 内容 |
|---|---|
| 認証 | 不要 |
| 通貨 | EUR / JPY (地域選択) |
| Anti-bot | 弱-中 |
| 画像権利 | 自前撮影推奨 |
| 在庫更新 | 比較的高頻度 |

### GIGLIO Outlet

| 項目 | 内容 |
|---|---|
| 認証 | 不要 (Outlet ページ) |
| 通貨 | EUR |
| Anti-bot | 中 |
| 画像権利 | 公式画像許諾要確認 |
| セール率 | 最大 -70% |

---

## 画像権利

BUYMA は**第三者 EC やブランド画像を許諾なく使用することを禁止**している
(規約第 11 条)。仕入先選定時から考慮しないと、安く仕入れられても出品段階で
リスクが残る。

### 対処パターン

1. **公式画像使用許諾**: ブランド公式・大手 EC (Farfetch 等) で
   出品者向け画像利用ポリシーを確認
2. **自前撮影**: 仕入れ後に自分で撮影 (推奨だが手間)
3. **転載可能サイト経由**: PR TIMES 等のメディア掲載写真

Phase 3-2 で **画像取得・加工・権利確認のフローを設計**予定。

---

## 次フェーズ (Phase 2c) 実装順序

### 優先度 1: Italist 1 社追加 (DDP)

- 仕入れ先抽象クラス `app/core/sources/base.py` を新設
- `BasebluSource` (DDU) を既存 scraper から切り出し
- `ItalistSource` (DDP) を新規実装
- `PricingParams.landed_cost_basis` 分岐で使い分け

### 優先度 2: 仕入れ優位スコア (source_edge)

```python
@dataclass
class SourceEdgeStats:
    cheapest_source: str
    cheapest_landed_cost_jpy: int
    second_cheapest_landed_cost_jpy: Optional[int]
    edge_jpy: int  # second - cheapest

def evaluate_source_edge(
    edge: SourceEdgeStats,
    final_price_jpy: int,
    min_edge_jpy: int = 10000,
    min_edge_ratio: float = 0.05,
) -> tuple[str, str]:
    # edge < max(¥10k, 売価×5%) → 価格競争に巻き込まれやすい → warn
    threshold = max(min_edge_jpy, int(final_price_jpy * min_edge_ratio))
    if edge.second_cheapest_landed_cost_jpy is None:
        return "pass", "exclusive_source"
    if edge.edge_jpy < threshold:
        return "warn", "low_source_edge"
    return "pass", "high_source_edge"
```

### 優先度 3: 順次拡大

- GIGLIO Outlet (DDU/DDP 不明 → 要検証)
- Antonioli (DDP)
- Tessabit (DDP)

### 優先度 4 (Phase 3): ブランド逆引き発掘

- LOW_COMPETITION_STRATEGY.md のターゲットブランドを起点に
  「ブランド名 + outlet/sale + 型番」で複数仕入先を探索
- 結果を `data/source_index.json` に蓄積

---

## 受容する事項 (技術スコープ外)

| 項目 | 理由 |
|---|---|
| 公式ブランド日本価格自動取得 | ブランドごとに異なる構造、Anti-bot 強。手動運用 |
| 国内百貨店 EC 価格自動取得 | 同上 |
| 小規模ブティック直接交渉 | 人手交渉タスク。技術自動化対象外 |

これらは**手動運用 (Top 候補のみ人手で確認)** で対応。

---

## 関連ドキュメント

- `docs/strategy/LOW_COMPETITION_STRATEGY.md` - 低競合ロングテール戦略
- `docs/review/REVIEW_RESPONSE.md` - ChatGPT Round 1 レビュー対応
- `docs/review/RESULTS_2026-04-26.md` - Phase 2a 実測結果
- `app/core/external_benchmark.py` - Phase 2b 外部ベンチマーク評価
- `scripts/fetch_farfetch_benchmarks.py` - Farfetch JP fetcher
