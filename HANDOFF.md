# 引き継ぎノート（2026-04-21 セッション終了時点 / 5回目更新）

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
- 直近コミット: `f9a0c84 feat(tags): Phase B 拡張 (~30 ルール) + カテゴリ別タグマスター追加`
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
  参考日本サイズ + 各行数量1 / 合計数量=行数
- **参考日本サイズのマッピング**:
  - CLOTHING: IT38 → S、IT40/42 → M、IT44/46 → L などアルファベットサイズ
  - FOOTWEAR: IT37.5 → 24cm、IT39.5 → 25.5cm など cm 単位
    (BUYMA 靴カテゴリは cm 単位の dropdown しか受け付けない)
- **マルチサイズ(2サイズ以上)**: 2026-04-20 に実機検証完了
  - 7fcf1dc: 行追加リトライ / data-bma-row-idx / per_row_qty vs total_qty 分離
  - 1d3bfa2: FOOTWEAR の cm 単位マッピング追加
  - FRANCESCO RUSSO Two-tone Pumps(IT37.5/39.5) で下書き保存成功
    (ID=131003231、画面目視で IT39.5→25.5cm, IT37.5→24cm 確認)

---

## ❌ 未解決 / 未検証の課題

### 1. 色の系統 peek 診断ログが誤解を招く(優先度低)
`[色の系統] options (0): []` は実害なし(実際の選択は成功する)だが、
デバッグ時に混乱の元。`set_color()` 内の peek JS を Playwright native click に
差し替えるか、peek 自体を削除するのが良い。

### 2. SA SU PHI は DOM では出るが未プログラム検証
2026-04-20 のマルチサイズ候補 #20 Sleevless Top (SA SU PHI, IT40/42) は
手動 DOM サジェストでは `SA SU PHI(サスファイ)` が表示されることを確認済み。
ただし実スクリプトで通したかは未確認(CDN で見つかる可能性が高いが、万一
見つからなければ DOM フォールバックが動作するはず)。必要になったら試す。

### 3. メンズ靴サイズマッピングが未検証
`_EU_SHOE_TO_JP_CM` は女性靴(EU 34〜41.5)の一般的なマッピング。男性靴
(EU 40〜46)や子供靴で出品する場合は `_map_footwear_to_jp_cm` の上限
再考と追加テストが必要(現状 >=42 は一律「27cm以上」)。

### 4. Phase 2 未着手
- 複数件の連続出品(`--limit N` で N>3 の動作)
- 公開出品(`draft_mode=False`) — 現状 draft のみ
- エラー時のリトライ戦略
- 日次バッチ実行

---

## 🎯 次セッションで優先して着手すべきこと

### 候補A: 複数件連続出品の安定性テスト (Phase 2 入口)
- `--limit 3〜5` で連続出品
- 途中失敗時に次商品へ進めるか (現状 brand_not_found などは PERMANENT_SKIP
  扱いで進む想定だが、連続実行での実機未検証)
- progress.json (succeeded / failed) の整合性
- 画像アップロード 403 や タイムアウト時の挙動
- 下書き連投時に BUYMA の rate limit が出ないか

### 候補B: 本公開フロー検証
- `publish_product()` の通し検証
- `--draft` なしで 1件出品 → すぐ削除の動作確認
- 公開時の必須フィールド validation を全部通すか

### 候補C: peek 診断ログ整理(小回り修正)
- `set_color()` 内の peek JS を削除、または Playwright native で書き直し
- `_click_select_option` 側に成功時のデバッグ出力を追加(現在は失敗時しか出ない)

### 候補D: 運用スクリプト整備
- 日次バッチ実行スクリプト(スクレイピング→フィルタ→出品)
- 失敗時の retry / ロギング
- 公開済み出品の価格更新・在庫追従

**おすすめは 候補A → 候補B の順**。まず下書き連続で安定性を見てから公開に進む。

---

## 🔑 今セッション(2026-04-21)で追加された知見

### 1. DeepL 翻訳統合 (.env から自動ロード)
- buyma_auto_listing.py 起動時に load_dotenv() を呼び DEEPL_API_KEY を読込
- DeepL Free プラン (50万字/月) でも品質十分。商品コメントが自然な日本語に
- _strip_accents() が NFD 分解で 濁点/半濁点 (U+3099/U+309A) まで剥がす
  バグを修正 (パンプス → ハンフス, ロゴ → ロコ になっていた)
  → JP combining marks をホワイトリストで保持 + NFC 再結合 (8159b84)

### 2. シーズン dropdown locator のリライト
- BUYMA は「シーズン」見出しを <p class="bmm-c-summary__ttl"> に置き、
  dropdown は兄弟の .bmm-l-col-9 カラム。従来は近い親しか見ていなかった
  ため見つからず → 厳密 textContent 一致 + 親を 8 階層登って .Select を
  含む祖先で抽出する方式に変更 (ac6d9d3)
- 候補ラベルは AW のみ年跨ぎ "2025-2026 AW" を最優先候補に追加 (4dd4fa4)

### 3. タグ自動付与 (Phase A → Phase B)
- a:has-text("一覧からタグを選択") でモーダル open、label.bmm-c-checkbox--tag
  内 .bmm-c-checkbox__body のテキストを正規化比較してチェック
- 全角/半角カッコ・角カッコ・空白を JS 側 norm() で揃えて誤判定を回避
  ("レザー(本革)" vs "レザー（本革）" 問題を解決) (ac6d9d3)
- Phase B: data/tag_reference.json にカテゴリ別タグマスターを保存
  (FOOTWEAR/BAGS/CLOTHING)。tags.json に約 30 ルール追加: 素材 (コットン
  /ウール/カシミヤ/シルク/リネン/デニム/ナイロン/キャンバス/サフィアーノ
  /クロコダイル/ラムスキン等)、柄 (レオパード/ゼブラ/ストライプ/ドット
  /花柄/カモフラージュ)、CLOTHING の袖 (ノースリーブ/半袖/長袖)、襟
  (Vネック/タートル/クルー) (ce7661c, f9a0c84)
- カテゴリ別 product_types で BUYMA 側に存在するタグだけ付与する仕組み
- 適切でないタグは出品取り下げリスクがあるため曖昧判定 (無地/ヒール高さ/
  トゥタイプ/スタイル) は意図的にスキップ

### 4. baseblu スクレイパー DETAILS タブ抽出
- body_html (DESCRIPTION タブ) にはマーケ文しか入っておらず、Sku/Season/
  Composition は別タブの DETAILS セクションに存在 → 出品時に season=空、
  description に "leather" 等のキーワードが無くタグ判定が動作しないバグ
- _extract_details_from_html() で Sku/Season/Composition をラベル正規表現
  で抽出し description_en に追記 (b932cbd)
- 商品ページに埋込 JSON (<script>) があり regex 先頭マッチで Sku が誤抽出
  される問題 → script/style ブロックを事前に剥がす方式に修正 (5a45f2f)

### 5. ログイン timeout 対策
- BUYMA はログイン後 WebSocket/polling で常時通信があり networkidle に
  到達しない → load 待機にしたが今度は URL 遷移が遅く誤検知
- 最終: page.wait_for_url(lambda url: signin/login 非含有, timeout=30s)
  で URL 変化を待つ方式に統一 (74622a0, 742615a)

---

## 🔑 前セッション(2026-04-20)の知見

### 1. マルチサイズ出品(2サイズ以上)のロジックは完成
- 行追加ボタン: 期待行数に達するまで最大2回リトライ + 実行数検証
- 行指定: `_tag_variation_rows()` で `data-bma-row-idx` 属性を振り、
  JS セット と Playwright locator を同一セレクタで引いて行ずれを排除
- 数量: `_set_stock_status_and_qty(per_row_qty, total_qty)` に分離。
  各行には 1、合計には 行数 を書く。単一サイズは同値で呼ぶため挙動不変
- FRANCESCO RUSSO Two-tone Pumps(IT37.5/39.5) で下書き保存(ID=131003231)成功

### 2. FOOTWEAR の参考日本サイズは cm 単位
BUYMA の靴カテゴリの「参考日本サイズ」dropdown は `21cm以下 / 21.5cm /
22cm / ... / 27cm以上` の cm 刻み。アパレル用の XS/S/M/L/XL を送ると
`候補なし` で click_failed する。
→ `_EU_SHOE_TO_JP_CM` + `_map_footwear_to_jp_cm()` で EU/IT 数値を cm に変換。
   `map_size_to_jp_reference(raw_size, product_type)` で product_type を
   見てディスパッチ。

### 3. CDN API の recall は不完全 → DOM サジェストフォールバック必須
baseblu のブティック系ブランドは CDN `cdn-suggest.buyma.com/brand_suggest`
で見つからないことがある。しかし BUYMA 本体の出品フォーム上の DOM サジェスト
には出るブランドもある(今回は AFTERCOAT/THE LATEST は両方×、FRANCESCO
RUSSO/SA SU PHI は DOM だけ出る)。
→ `resolve_brand()` は CDN 未ヒット時に unregistered に自動追加せず -1 を返し、
   `select_brand()` は brand_id <= 0 でも DOM サジェストを試す(完全一致のみ)。
   確定的な除外は `brands.json.unregistered` に手動追加する運用。

### 4. 2026-04-20 時点の brands.json 実績
- `brands` に 72 エントリ(FRANCESCO RUSSO など CDN 自動登録分含む)
- `unregistered`: `["AFTERCOAT", "THE LATEST"]` (BUYMA に存在しないことを
  手動 DOM 検索で確認済み)

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
- **Phase 1（全フィールド正しく入力）**: ✅ 完全クリア
  - 単一サイズ・マルチサイズ両対応 / CLOTHING XS-XXL / FOOTWEAR cm
  - DeepL 翻訳で商品コメントが自然な日本語
  - シーズン (年跨ぎ AW 表記対応) 自動設定
  - タグ Phase B (素材/柄/袖/襟 ~30 ルール) で閲覧率 UP 対策
  - CDN 未ヒットブランドの DOM サジェストフォールバック
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
