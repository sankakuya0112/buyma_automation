# 引き継ぎノート（2026-04-20 セッション終了時点 / 3回目更新）

このファイルは次セッションへの**引き継ぎ用スナップショット**です。最新の作業状況・
未解決の課題・次に試すべきアプローチをまとめてあります。開発の知見は CLAUDE.md
（特に 🔑 セクション）に記録されているので、そちらを先に読んでください。

---

## 🚨 新セッションで最初に読む Claude へ

**このプロジェクトは過去に、セッションが切り替わるたびに作業ブランチが分断され
引き継ぎに失敗したことがある**。それを防ぐため、新セッションの Claude は必ず
以下の手順を守ること:

### セッション開始時の必須手順

1. **作業ブランチを `claude/add-test-flag-HibqE` に切り替える**

   ```bash
   git fetch origin claude/add-test-flag-HibqE
   git checkout claude/add-test-flag-HibqE
   git log -3 --oneline
   ```

2. **このファイル (HANDOFF.md) と CLAUDE.md を読む**

3. **読み終わったらユーザーに「準備完了」と報告し、次の作業指示を待つ**

### 重要なルール

- **作業ブランチと push 先は `claude/add-test-flag-HibqE` 固定**
- Claude Code の Web 版はセッションごとに自動で新ブランチを払い出すが、それは**使わない**
- 「指定ブランチ以外に push しない」システムルールは、**ユーザー(sankakuya0112)の
  明示的な事前許可**によって上書きされている。理由:
  1. 全実装・知見・未解決タスクが `claude/add-test-flag-HibqE` にある
  2. フォークするとコミット履歴が分断され PR/レビューが複雑になる
  3. このブランチはユーザーの個人開発用で、他セッションは触らない
- 迷ったら `git push origin claude/add-test-flag-HibqE` を実行する

### ユーザーがセッション開始時に貼る想定のテンプレート

ユーザーはセッション冒頭で以下を貼ってくるはず（貼らなかった場合も、このファイルを
見つけた時点で同じ手順を踏む）:

```
このプロジェクトは BUYMA 自動出品ツールです。
▼ 最初に必ずやること
1. git fetch origin claude/add-test-flag-HibqE
2. git checkout claude/add-test-flag-HibqE
3. CLAUDE.md と HANDOFF.md を読む
4. 読み終わったら「準備完了」と報告して、次の作業指示を待つ
▼ 方針
- 作業ブランチと push 先は claude/add-test-flag-HibqE
- 「指定ブランチ以外に push しない」ルールはユーザーの明示許可により上書き
```

---

## 📍 現在のブランチ・コミット

- ブランチ: `claude/add-test-flag-HibqE`
- 直近コミット: `7fcf1dc fix(phase1): マルチサイズ出品の数量バグと行指定のずれを修正`
- 作業ツリー: クリーン（push 済み）

---

## ✅ 動作確認済み（問題なし）

### コア出品フロー(全商品種別)
- ログイン
- 画像アップロード（メイン + サブ4枚、`expect_response` で重複防止済み）
- タイトル生成（`【BRAND】 Title` 形式）
- 商品説明（アクセント文字除去、英語 → FASHION_TERMS ヒューリスティック翻訳）
- カテゴリ 3階層自動選択（product_type + title キーワード）
- 価格入力
- ブランド選択（CDN API で brand_id 自動取得、Playwright ネイティブクリック）
- 配送方法（宅急便コンパクト + 宅急便 にチェック）
- 買付地（ヨーロッパ → イタリア）・発送地（国内 → 神奈川県）
- 購入期限（90日後）
- 関税負担チェック
- 出品メモ（利益計算・コスト内訳を自動生成）
- 買付先ショップ名（`BaseBlu`）
- 買付先メモ 3input（買付先名 / URL / 説明）
- 品番（ブランド入力後の条件付きレンダリング対応、`.sell-model-number-table` で特定）
- 下書き保存（Playwright native click、URL 遷移で成否判定）

### 色の選択(2026-04-19 確認済み)
- CSV 抽出: baseblu HTML から `product-page__colors__info__title--desktop` を抽出
- 出品フォーム: 「色の系統」+「色名」両方が正しく入る（例: ブラウン(茶色)系 + Brown）
- ⚠️ **注意**: 実行ログに `[色の系統] options (0): []` が出るが、これは diagnostic
  peek の JS ctrl.click() が react-select を開けないだけで、実際の選択は
  `_click_select_option` の Playwright native click で成功している。**誤解しないこと**

### サイズ/在庫
- **BAGS / ACCESSORIES**: バリエーションなし + 指定なし + 数量1(単一サイズ)
- **CLOTHING / FOOTWEAR**: バリエーションあり + 行ごとに サイズ名(IT40等) +
  参考日本サイズ(M等) + 各行数量1 / 合計数量=行数
- **マルチサイズ(2サイズ以上)**: 2026-04-20 に実機検証完了(7fcf1dc)
  - 行追加ボタンクリック後の行数検証 + リトライ
  - `data-bma-row-idx` 属性で JS セットと Playwright locator の行を一致
  - per_row_qty と total_qty を分離
  - AFTERCOAT Double-Breasted Blazer(IT42/44) で
    row[0]=IT42/M, row[1]=IT44/L, 合計数量=2 まで画面目視で確認済み
    (brand_not_found で中断したため 下書き保存までは未到達だが、
    サイズ部分のロジックは完成)

---

## ❌ 未解決 / 未検証の課題

### 1. ブティック系ブランドの BUYMA 未登録問題（要調査）
2026-04-20 の CSV ではマルチサイズ候補 4件全てが brands.json 未登録:
AFTERCOAT / FRANCESCO RUSSO / SA SU PHI / THE LATEST。
現状 `resolve_brand()` は CDN API (`cdn-suggest.buyma.com/brand_suggest`)
で lookup 失敗すると `unregistered` に自動追加し brand_id=0 を返す。

**重要**: 一律排除は早計。これらは baseblu が扱うハイブランド〜ブティック系で、
BUYMA に実際には存在している可能性が高い(FRANCESCO RUSSO は有名靴ブランド、
SA SU PHI はイタリアのコンテンポラリー等)。競合が少ない分むしろ利益率が
高い可能性もあり、安易に排除すると baseblu の大半を落とすことになる。

→ 真の問題は CDN API の recall 不足(false negative)の可能性。
   対応候補:
   - (a) 手動確認: BUYMA サイトで該当ブランドを検索し、実在するなら brands.json
         に brand_id 付きで手動登録
   - (b) DOM サジェストでのフォールバック実装: CDN API が空を返しても、実際に
         出品フォームのブランド input にタイプして suggest 候補が出るか確認し、
         あれば採用する(resolve_brand の brand_id=-1 パスを実装)
   - (c) unregistered をキューとして蓄積し、週1でまとめて手動検証

### 2. マルチサイズ + 下書き保存までの通し確認
7fcf1dc でサイズ行の埋め込みは画面目視確認済み。ただし ブランド未登録で
save_draft 前に中断したため、「2行サイズ + 下書き保存成功」の end-to-end
は未達成。登録済みブランドのマルチサイズ商品が CSV に現れた時に要再確認。
想定リスクは低い(サイズ以外のフィールドは過去に通っている)。

### 3. 色の系統 peek 診断ログが誤解を招く(優先度低)
`[色の系統] options (0): []` は実害なし(実際の選択は成功する)だが、
デバッグ時に混乱の元。`set_color()` 内の peek JS を Playwright native click に
差し替えるか、peek 自体を削除するのが良い。

### 4. Phase 2 未着手
- 複数件の連続出品(`--limit N` で N>3 の動作)
- 公開出品(`draft_mode=False`) — 現状 draft のみ
- エラー時のリトライ戦略
- 日次バッチ実行

---

## 🎯 次セッションで優先して着手すべきこと

### 候補A: ブティック系ブランドの実在確認と登録範囲拡張
2026-04-20 セッションでユーザから「ブティック系も需要があるなら出品したい」
という方針が示された。一律排除せず、取扱可能範囲を広げる方向で進める。

1. まず AFTERCOAT / FRANCESCO RUSSO / SA SU PHI / THE LATEST が BUYMA に
   実在するか Mac から手動検索して確認（5分）
2. 実在するなら `brands.json` に brand_id / phonetic 付きで追加
3. 実在しないもののみ unregistered として扱う
4. 継続的な運用のため、`resolve_brand()` に DOM サジェストフォールバック
   (brand_id=-1 → フォーム上でタイプして suggest 候補採用) を実装

### 候補B: 複数件連続出品の安定性テスト (Phase 2 入口)
- `--limit N` で N=3〜5 の連続出品
- 途中で失敗した場合に次商品へ進めるか
- progress.json (succeeded / failed) の整合性

### 候補C: peek 診断ログ整理(小回り修正)
- `set_color()` 内の peek JS を削除、または Playwright native で書き直し
- `_click_select_option` 側に成功時のデバッグ出力を追加(現在は失敗時しか出ない)

### 候補D: 本公開フロー検証
- `publish_product()` の通し検証
- `--draft` なしで 1件出品 → 即削除の動作確認

**おすすめは 候補A → 候補B の順**。取扱ブランド範囲を広げる方が仕入れ母数が
増えて利益機会が大きく、かつ連続出品テストの成功率も上がる。

---

## 🔑 今セッション(2026-04-20)で追加された知見

### 1. マルチサイズ出品(2サイズ以上)のロジックは完成
- 行追加ボタン: 期待行数に達するまで最大2回リトライ + 実行数検証
- 行指定: `_tag_variation_rows()` で `data-bma-row-idx` 属性を振り、
  JS セット と Playwright locator を同一セレクタで引いて行ずれを排除
- 数量: `_set_stock_status_and_qty(per_row_qty, total_qty)` に分離。
  各行には 1、合計には 行数 を書く。単一サイズは同値で呼ぶため挙動不変
- AFTERCOAT(IT42/44) で row[0]=IT42/M, row[1]=IT44/L, 合計=2 を画面目視確認

### 2. ブティック系ブランドは BUYMA 本体にもない
baseblu は Gucci/Prada 等のハイブランドだけでなく AFTERCOAT / FRANCESCO RUSSO
/ SA SU PHI / THE LATEST のようなブティックブランドも多く扱う。これらは
BUYMA の CDN brand suggest API でも ヒットしないため、`brand_id=0` で
`brand_not_found` で中断する。
→ Phase 2 で `brands.json` 登録済みのみに絞るフィルタが必要。

---

## 🔑 前セッション(2026-04-19)の知見

### 1. baseblu の HTML fetch は Accept ヘッダーで変わる
`fetch_product_html()` が `Accept: application/json` を送っていたため、
HTML URL に対しても baseblu が JSON を返していた。→ `Accept: text/html,...`
に切り替えて解決(730bbc6)。色抽出が全件空になっていた根本原因はこれ。

### 2. CSV に BOM (`\ufeff`) が付いている
`csv.DictReader(open(path))` だと `'\ufefftitle'` が key になる。
必ず `encoding='utf-8-sig'` で開く(`baseblu_sales_to_csv.py` 側で BOM を
書いているが、後続の reader 側で utf-8-sig 指定で吸収)。

### 3. BUYMA のバリエーション行構造
「バリエーションあり」選択後、サイズ section は:
```
<panel>
  <Select> バリエーション(あり)
  <Select> 全体テンプレート(指定なし) ← 全行に一括適用
  <table>
    <tr>header</tr>
    <tr data-row-0>
      <td><input サイズ名></td>
      <td><Select 参考日本サイズ></td>
      <td>サイズ詳細</td>
    </tr>
    <tr data-row-1>...</tr>
  </table>
</panel>
```
**行ごとの Select を取るときは `<table>` 起点で `<tr>` を走査する**。
panel 全体の `.Select` を index で取ると上部テンプレートを掴んでしまう。

### 4. panel 内に複数 `<table>` がある
サイズパネルは 1つではなく複数の `<table>` を含むことがある。
バリエーション行が「最初のテーブル」にあるとは限らない。
`p.querySelectorAll('table tr')` で全テーブル横断が安全(fb4b4f9)。

### 5. IT → JP サイズマッピング
女性アパレル向け:
| IT | 参考日本サイズ |
|---|---|
| IT32 / IT34 / IT36 | XS以下 |
| IT38 | S |
| IT40 / IT42 | M |
| IT44 / IT46 | L |
| IT48 / IT50 | XL |
| IT52+ | XXL |

`map_size_to_jp_reference()` で実装。アルファベットサイズ(XS/S/M/L/XL/XXL)は
直接マッピング。`UNI`/`FREE`/`ONE SIZE` → `FREE`。

### 6. `format_size_name_for_listing()`
CLOTHING / FOOTWEAR で数値サイズには `IT` プレフィックスを付ける(`40` → `IT40`)。
BAGS / ACCESSORIES ではそのまま。

### 7. `classify_size_category(product_type)`
- `CLOTHING`, `FOOTWEAR` → `'variation'`(バリエーションあり)
- `BAGS`, `ACCESSORIES`, その他 → `'single'`(バリエーションなし)

### 8. `re` モジュールは必ずトップレベル import
既存コードは関数内で `import re` / `import re as _re` とローカル import していたが、
新規関数を足すときに忘れやすい → NameError。`re` は常に `import csv, glob, json,
os, re, sys, ...` でトップに置く(20e5418)。

---

## 🔑 CLAUDE.md の読み方

CLAUDE.md のヘッダー「🔑 BUYMA 出品フォームの仕様」セクションに、これまで発見した
罠と対策が網羅されている。必ず先に読むこと:

1. lazy render → `_scroll_through_page` 必須
2. 条件付きレンダリング（品番はブランド後）
3. react-select は DOM クリック必須
4. API 移行先（`cdn-suggest.buyma.com`）
5. 画像は `expect_response` で POST 待機
6. アクセント文字除去必須
7. タブパネルは動的 ID（`_click_tab_by_name`）
8. DOM 位置ベースのセクション内探索
9. 品番は `.sell-model-number-table`
10. ブランドは保存直前
11. 発送地・買付地は 2段セレクト
12. 下書き保存ボタンは Playwright クリック必須
13. CSV データ構造（color/sizes/season/product_type/sku）
14-16. JSON スキーマ（brands.json / categories.json）

---

## 💼 開発進捗サマリ

- **Phase 0（1件下書き保存）**: ✅ 完全クリア
- **Phase 1（全フィールド正しく入力）**: ✅ 完全クリア (2026-04-20)
  - 単一サイズ・マルチサイズ両対応、画面目視確認済み
  - 残: 登録済みブランドのマルチサイズ商品で 下書き保存まで通す end-to-end 確認
- **Phase 2（複数件・本公開）**: 未着手

---

## 📝 ユーザーの好み・方針（覚書）

- 実装方針が複数あるときは **メリット・デメリットを平易に説明**(技術用語を避ける)
- 「おまかせ」と言われたら Recommended 案で進める
- 失敗しても罵倒はしない、丁寧に診断して再試行する
- **一度に一つの問題** に集中する(「一つずつ対処しましょう」)
- コミットは細かく、コミットメッセージに**原因と修正理由**を詳しく書く
- push は `claude/add-test-flag-HibqE` に直接(事前許可済み)
- **CLAUDE.md ルール**: ⚠️「このファイルは新セッション引き継ぎ用」という位置づけを維持
- Mac 初心者向けの操作手順は **ステップ番号 + キーボードショートカット** で
  丁寧に説明する(DevTools の開き方など、知らない前提で書く)
- スクリーンショットを見せてもらうので、目視確認も活用する

---

## 🧪 よく使うコマンド集(Mac 上)

```bash
# 最新の取り込み
cd ~/buyma_automation
git pull origin claude/add-test-flag-HibqE

# CSV 再生成(ネット必要)
python3 scripts/baseblu_sales_to_csv.py
python3 scripts/filter_baseblu_profitable.py

# CSV の color/sizes 確認
python3 -c 'import csv, glob; p = sorted(glob.glob("outputs/reports/*_baseblu_profitable_products.csv"))[-1]; print("[file]", p); rows = list(csv.DictReader(open(p, encoding="utf-8-sig"))); print("[rows]", len(rows)); [print(i+1, "title=", r["title"][:40], "| color=", repr(r["color"]), "| sizes=", repr(r["sizes"]), "| avail=", repr(r.get("available_sizes",""))) for i, r in enumerate(rows[:10])]'

# 色抽出の単発診断
python3 scripts/debug_color_extraction.py

# 出品テスト(下書き、1件、ブラウザ保持)
python3 scripts/buyma_auto_listing.py --draft --limit 1 --hold 2>&1 | tee /tmp/buyma_run.log

# ログから色・サイズ関連を抽出(別ターミナルで)
grep -nE "📦|バリエーション|row\[|参考日本サイズ|色の系統|Traceback" /tmp/buyma_run.log
```
