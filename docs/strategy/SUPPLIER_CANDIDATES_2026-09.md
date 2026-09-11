# 仕入先候補の選定と組込み可否 (2026-09-11 調査)

**目的**: baseblu.com / italist.com と同種の「海外ファッション小売・アウトレット EC」から、
日本向けに安く仕入れられ、かつ既存パイプライン (Python + requests、Shopify `/products.json` 解析)
に `Source` として組み込めるサイトを選び、優先順位を付ける。

**調査方法と限界**: Claude Code クラウドからは各ショップサイトへの直接アクセスが遮断されている
(egress 制限) ため、**Web 検索のスニペットと二次記事 (公式ヘルプ・邦人ブログ・技術ブログ) に基づく**。
数値・条件はすべて **2026-09-11 時点のスニペット情報で未検証**。「不明」は根拠が見つからなかった項目。
最終判断は §6 の Mac 検証手順で確定させること。

---

## 1. 結論 (先に読む)

| 優先 | サイト | 帯 | 日本発送 / 関税 | 自動取得 | 推す理由 | 要検証 |
|---|---|---|---|---|---|---|
| **A-1** | antonioli.eu (ミラノ) | ラグジュアリー + コンテンポラリー | ○ / DDP か DDU か情報が矛盾 | **Shopify 系 (URL 構造)** → `products.json` 期待 | 日本語 UI・JPY 表示・PayPal と個人購入向けの整備が進んでおり、baseblu と同型の「単一在庫ブティック」。BUYMA 定番仕入先リストに載っていない | 関税込みか、EU 域外向け VAT 控除か、`products.json` の公開状態 |
| **A-2** | monnierparis.com (パリ) | バッグ・小物・靴 (回転の速い帯) | ○ / **DDU** (税・関税は配送業者から別途請求) | **Shopify 系 (URL 構造)** | 小物専門で低単価帯の候補が多い。Express $40 と送料が明確 | VAT 控除表示の有無、`products.json` |
| **A-3** | slamjam.com (ミラノ) | コンテンポラリー・スニーカー | ○ (UPS 約 1 週間の実例) / DDU の可能性 | **Shopify 系 (URL 構造)** | Our Legacy / Salomon / New Balance 系の回転帯。BUYMA 競合が薄い | 日本向け送料・関税、`products.json` |
| **B-1** | giglio.com (パレルモ) | ラグジュアリー + コンテンポラリー | ○ / DDU 寄り (UPS が配達時徴収の情報) | 不明 (Zendesk FAQ、独自基盤の可能性) | **EU 域外向けに VAT 22% 控除価格を表示** = baseblu と同じ原価構造。送料無料閾値 ¥63,313 (邦人ブログ)。PayPal 可 | 取得手段 (JSON-LD / HTML)、実際の DDP/DDU |
| **B-2** | tizianafausti.com (ベルガモ) | ラグジュアリー | ○ (DHL/UPS Express、公式に日本記載) / 不明 | 不明 (独自 `/us_en/` ロケール) | **€200 以上で送料無料** (公式)、送料目安 ¥3,500。低単価品の送料負けを避けやすい | DDP/DDU、VAT 控除、取得手段 |
| **B-3** | julian-fashion.com / spinnakerboutique.com | ラグジュアリー | ○ / **DDU** (公式 policy) | 独自基盤 (両者同一の `/en-XX/policy/` 構造 → 1 パーサで 2 サイト) | 日本人バイヤーの少ないリミニ/ミラノ・マリッティマ系 | 取得手段、VAT 控除、返品時の送料・関税不返金 |
| C | luisaviaroma.com | ラグジュアリー | ○ / **DDP** (複数の邦人ブログが一致)、Express €31 | **難** (Akamai Bot Manager を公式事例で確認) | 手動仕入れの比較先としては優秀。自動取得は諦める | — |
| C | baltini.com / hbx.com / kith.com | 米・香港、DDP | ○ / DDP (関税込み・送料無料 or チェックアウト時確定) | baltini は Shopify 系、他は不明 | 着地コストが確定するので「相場比較・手動仕入れ」用 | DDP 価格が baseblu 比で割高になりやすい点 |
| 見送り | farfetch / ssense / mytheresa / yoox / theoutnet / mrporter / cettire | — | ○ (多くは DDP) | **難〜不可** (Farfetch: JS+CAPTCHA、SSENSE: 自社 bot 対策、YNAP 系: Salesforce Commerce Cloud で JSON なし、cettire: 自社基盤) | BUYMA ショッパーの定番で価格優位が出にくい。Mytheresa は転売疑いで注文拒否の規約、Farfetch は転売購入をポイント対象外と明記 | — |
| 不可 | breuninger.com / matchesfashion.com | — | breuninger は日本直送不可。MATCHES は 2024 年破産後、2026 年再始動予定で停止中 | — | — | — |

**まず着手する 3 サイト**: A-1 antonioli.eu → A-2 monnierparis.com → A-3 slamjam.com。
理由は「Shopify 系なら既存の解析コードがそのまま使え、Mac で 1 コマンド検証できる」から。
B 群は条件が良い (VAT 控除・送料無料閾値) が取得手段の新規実装が要るので、A 群で成果が出てから。

---

## 2. 候補サイト比較 (イタリア・欧州ブティック)

| サイト | 国 | 日本発送 | DDP/DDU | VAT 免税表示 | 送料 / 無料閾値 | 通貨/JPY | 決済 | 返品 | 推定基盤 | 出典 |
|---|---|---|---|---|---|---|---|---|---|---|
| antonioli.eu | 伊 | ○ | 矛盾 (公式 Shipping 頁: 税込国リストに日本なし → DDU 寄り / 邦人ブログ: 日本語画面で関税込み表示) | 不明 | 不明 | 日本語・JPY 表示ありの情報 | PayPal | 不明 | Shopify 系 (`/en-us/pages/`) | antonioli.eu/en-us/pages/shipping, ready-to-wear.jp |
| julian-fashion.com | 伊 | ○ | DDU (米/UAE/豪/伯/墨/英以外は配達時課税、公式) | 不明 | 標準便のみ無料条件あり | 不明 | 不明 | 返品時の送料・関税は返金対象外 (公式) | 独自 (`/en-US/policy/`) | julian-fashion.com/en-US/policy/condshp |
| spinnakerboutique.com | 伊 | ○ | DDU 寄り (配達時 UPS が関税 $86 徴収の口コミ) | 不明 | 不明 | 不明 | 不明 | 返品時関税は不返金 (口コミ) | 独自 (Julian と同型) | spinnakerboutique.com/en-US/policy/condret, Trustpilot |
| giglio.com | 伊 | ○ | DDU 寄り (UPS 配達時に関税・消費税) | **あり (非 EU 向け 22% 控除)** | **¥63,313 以上で無料** (邦人ブログ) | 不明 | PayPal (3 回払い可) | 不明 | 不明 (FAQ は Zendesk) | thegoods.jp, faq.giglio.com |
| tizianafausti.com | 伊 | ○ (DHL/UPS Express) | 不明 | 不明 | **目安 ¥3,500 / €200 以上無料** (公式) | 不明 | 不明 | 不明 | 独自 (`/us_en/`) | tizianafausti.com/us_en/shipment |
| eleonorabonucci.com | 伊 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 独自 (Tiziana Fausti と類似) | eleonorabonucci.com/en/shipment |
| michelefranzesemoda.com | 伊 (ナポリ) | ○ (推定) | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | **Shopify 系** (`/en/pages/spedizione`) | michelefranzesemoda.com/en/pages/spedizione |
| monnierparis.com | 仏 | ○ | **DDU** (公式) | 不明 | **Express $40** (公式) | 不明 | 不明 | 不明 | **Shopify 系** (`/pages/delivery`) | monnierparis.com/pages/delivery |
| luisaviaroma.com | 伊 | ○ | **DDP** (邦人ブログ複数一致) | 税込のため非表示 | **Express €31 一律** | 不明 | 不明 | 不明 | 不明。**Akamai Bot Manager** | fashion.spider.jp, akamai.com/customer-story/luisa-via-roma |
| baltini.com | 米 (伊ブティック在庫) | ○ | **DDP** (公式「送料無料・関税込み」) | 不明 | 無料 | 不明 | 不明 | 不明 | **Shopify 系** (`/pages/orders-and-shipping-1`) | baltini.com/pages/orders-and-shipping-1 |
| genteroma.com / biffi.com | 伊 | ○ (世界発送・口コミ) | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | genteroma.com/en, Trustpilot |
| tessabit / leam / coltorti / d'aniello / forzieri | 伊 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 不明 | 一次情報なし |
| breuninger.com | 独 | **×** (発送国に日本なし) | — | — | — | — | — | — | — | faq.eu.breuninger.com |

---

## 3. 候補サイト比較 (大手ラグジュアリー EC)

| サイト | 国 | 日本 | DDP/DDU | 送料 / 無料閾値 | JPY | 転売・リセラー | 自動取得 | 出典 |
|---|---|---|---|---|---|---|---|---|
| mytheresa.com | 独 | ○ | DDP | ¥80,000〜90,000 以上無料 (記事差) | ○ | **返品率 70% 超・商業転売の疑いで注文拒否 (規約)** | 不明 (中) | mytheresa.com/us/en/customer-care/shipping, terms-conditions |
| farfetch.com | 英 | ○ | DDP 標準 (DAP 選択可) | 不明 | ○ | **転売目的購入はポイント対象外と明記**、まとめ買いキャンセル報告 | **難** (JS + CAPTCHA) | farfetch.com/orders-and-shipping/, crawlbase.com |
| cettire.com | 豪 | ○ | 不明 (記事差) | ¥30,000 以上無料 | 不明 | 品質・配送苦情多数 (Trustpilot 低評価) | 中 (自社基盤) | trustpilot.com/review/www.cettire.com, livewiremarkets.com |
| ssense.com | 加 | ○ | DDP | ¥35,000 以上無料 | ○ | 不明 | **難** (自社 bot 対策を技術ブログで公言) | kikidune.com/shop/ssense, medium.com/ssense-tech |
| yoox.com | 伊 | ○ | DDP (関税・税・通関料込み) | ¥20,000〜48,000 無料 (記事差) | 不明 | 不明 | 中〜難 (**Salesforce Commerce Cloud**、`products.json` なし) | clip-fashion.net/yoox-kaikata/, enlyft.com/tech/company/ynap.com |
| mrporter / net-a-porter | 英 | ○ | DDP | NAP: USD 500 以上速達無料 | 不明 | 不明 | 中〜難 (SFCC) | net-a-porter.com/en-jp/content/help/delivery/ |
| theoutnet.com | 英 | 不明 (投資グループへ売却後) | 不明 | 不明 | 不明 | 不明 | 中〜難 (SFCC) | businessoffashion.com |
| italist.com | 伊 | ○ | DDP | 無料 | 不明 | 直接の制限報告なし。「関税込みで現地直買いより割高」との指摘 | 既存: セール collection が gating、compare_at_price が null (HANDOFF) | thetruescents.com/italist-how-to-shop/ |
| 24s.com | 仏 | ○ | 不明 | 不明 (返品送料無料) | 不明 | 不明 | 不明 | 24s.com/en-us/your-24s/shipping-and-returns |
| END. | 英 | ○ | **DDU** (日本向け明記) | 不明 | 不明 | 不明 | 不明 | endclothing.com/jp/delivery |
| matchesfashion.com | 英 | **停止中** (2024 破産、Hulcan が 2026 再始動予定) | — | — | — | — | — | fashionista.com/2025/12/matches-newly-acquired-by-hulcan |

---

## 4. 候補サイト比較 (コンテンポラリー・スニーカー帯)

| サイト | 国 | 日本 | DDP/DDU | 送料 | セール | 基盤 | 制限 | 出典 |
|---|---|---|---|---|---|---|---|---|
| slamjam.com | 伊 | ○ (UPS 約 1 週間) | DDU の可能性 | 不明 | 不明 | **Shopify 系** (`/en-us/policies/`) | 不明 | slamjam.com/en-us/policies/shipping-policy |
| hbx.com | 香港 | ○ (FedEx / 佐川) | **DDP 的** (チェックアウトで関税計算) | 返品送料 HBX 負担 | あり | 不明 | 不明 | hbx.com/delivery |
| kith.com | 米 | ○ | **DDP** (Global-E) | 不明 | 稀 | 不明 | 限定品は抽選 (1 人 1 エントリー) | kith.com/pages/international-orders |
| juicestore.com | 香港 | 要問合せ | DDU | 不明 | あり | **Shopify 系** | 不明 | juicestore.com/collections/sale |
| goodhoodstore.com | 英 | 世界発送 (日本個別記載なし) | 不明 | 不明 | 不明 | **Shopify 系** | 不明 | goodhoodstore.com/en-us |
| yoox.com (Golden Goose 等) | 伊 | ○ | DDP | 上記 | -22〜-30% 実例 | SFCC | — | yoox.com |
| footpatrol / size? (JD 系) | 英 | 国際配送あり | DDU 的 | 不明 | あり | 不明 | 不明 | footpatrol.com/pages/international-delivery |
| sneakersnstuff / tres-bien / 43einhalb / bstn / solebox / overkill | 北欧・独 | 欧州外 UPS 等 (日本個別記載なし) | 不明〜VAT 控除表示 (Très Bien) | 不明 | 不明 | 不明 | 不明 | 各社 shipping 頁 |
| Dover Street Market (ロンドン) | 英 | ○ (DHL Express) | 不明 | 不明 | 基本フルプライス | 不明 | 不明 | shop.doverstreetmarket.com |

---

## 5. 原価モデルへの反映事項 (app/core/pricing.py)

調査で得た数値のうち、現行モデルに**入っていない / ズレている**もの:

| 項目 | 調査結果 (snippet-based) | 現行 | 対応 |
|---|---|---|---|
| 通関立替手数料 (DDU 仕入れ) | DHL 等: **1 件 ¥3,300 または関税等の 2% の高い方** | **未計上** | `PricingParams` に `customs_handling_jpy` を追加し、DDU の Source では ¥3,300 を既定にする。baseblu にも該当 |
| 革靴の関税 | **30% または 1 足 ¥4,300 の高い方** (少額免税対象外)。EU 原産は EPA 無税の対象外 | boots 17% / loafers・pumps 17% / shoes 10% | 革製アッパーの靴 (boots / loafers / pumps / heels) を 30%・最低 ¥4,300 に。sneakers (布・合成) は 8% のまま |
| 革バッグの関税 | 10〜20% 前後 (品目差) | 8% | 実インボイスで検証してから調整 (現行 8% は過小の可能性) |
| 輸入消費税 | 10%、(商品 + 送料 + 保険) に課税 | 10% | 課税ベースに送料が含まれているか確認 |
| 課税ベース | 個人輸入は「小売価格 × 0.6」、商業輸入は全額 | 不明 | 転売目的は商業扱いになり得る。税務は専門家確認 (要注意事項として記録) |
| 海外決済手数料 | 通常カード 2〜3% → Wise / Revolut で ≈0% | 2.2% | Wise/Revolut を使うなら Source の `purchase_fx_fee_rate` を 0 に |
| CITES 素材 | ワニ・パイソン・象革は個人輸入でも許可が必要 | judge タスクの `restricted_material` で skip | 維持 |

出典: live-commerce.com (立替手数料), hi-japan.com/leather-shoes, hunade.com/kawagutsu-zeiritsu, hunade.com/trade-tools/personal-import-tax, koyano-cpa.gr.jp/nobiyo-kaikei/column/5618/, hunade.com/leather-cites-judgement, revolut.com/ja-JP/blog

---

## 6. Mac での検証手順 (A 群 3 サイト)

サーバーからは接続できないため、以下は **Mac で** 実行する。1 サイト 5 分程度。

```bash
cd ~/buyma_automation

# 1) Shopify かどうか: JSON が返れば Shopify。403 / HTML が返れば非 Shopify か bot 対策あり
curl -s -o /dev/null -w "%{http_code}\n" "https://antonioli.eu/collections/all/products.json?limit=1"
curl -s "https://antonioli.eu/collections/all/products.json?limit=1" | head -c 400; echo
curl -s "https://monnierparis.com/collections/all/products.json?limit=1" | head -c 400; echo
curl -s "https://slamjam.com/collections/all/products.json?limit=1" | head -c 400; echo

# 2) セール collection の handle を探す (JSON が返るサイトのみ)
curl -s "https://antonioli.eu/collections.json?limit=250" | python3 -c "import sys,json; [print(c['handle']) for c in json.load(sys.stdin)['collections'] if 'sale' in c['handle'] or 'outlet' in c['handle']]"

# 3) 通貨: Shopify Markets はロケール付き URL で通貨が変わることがある (JPY で返れば FX 手数料 0 扱いにできる)
curl -s "https://antonioli.eu/en-jp/collections/all/products.json?limit=1" | python3 -c "import sys,json; p=json.load(sys.stdin)['products'][0]; print(p['title'], p['variants'][0]['price'], p['variants'][0].get('compare_at_price'))"

# 4) robots.txt に /collections や /products.json の Disallow が無いか
curl -s https://antonioli.eu/robots.txt | head -40

# 5) ブラウザでチェックアウト直前まで進め、日本宛の「関税込みか」「VAT が引かれているか」「送料」を確認
#    (baseblu と同じ DDU + VAT 控除なら BasebluSource と同じ設定で組み込める)
```

**判定基準**
- 1) で JSON が返り、2) でセール handle が見つかり、4) で Disallow なし → **組込み可 (易)**。
  `app/core/sources/<name>.py` を BasebluSource を雛形に作り、取得スクリプトは italist 用を
  URL / 商品 URL / メタ (通貨・DDP/DDU・VAT・送料) をパラメータ化して流用する
  (提案: `scripts/shopify_sales_to_csv.py --source <name>` + `data/sources.json`)。
- JSON が返らない → HTML 内の JSON-LD (`application/ld+json`) を確認。あれば **中**。
- 403 / CAPTCHA → **難**。手動仕入れの比較先に回す。

---

## 7. 見送り理由の要約

- **BUYMA 定番仕入先 (Farfetch / YOOX / NAP / SSENSE / Mytheresa)** は多数のショッパーが使うため
  価格優位が出にくい (ec-navi.com, us-buyer.com)。加えて自動取得が難しく、Mytheresa は転売疑いの
  注文拒否、Farfetch は転売購入のポイント除外を規約に明記している。
- **DDP サイト** (italist / luisaviaroma / baltini / HBX) は着地コストが確定して事故は少ないが、
  関税・消費税が価格に織り込まれる分、baseblu 型 (VAT 控除 + DDU) より原価が高くなりやすい。
  「相場の確認」と「baseblu に在庫が無いときの手動仕入れ」用に位置づける。
- **穴場として記事に挙がるが未確認**: G&B Negozio (VIP 割引 + VAT 控除)、d'Aniello、
  ドイツの veryPOOLish (the-buyers.jp, webdeki.com)。次回の調査候補。

---

## 8. 出典一覧 (主要)

- antonioli.eu/en-us/pages/shipping / ready-to-wear.jp
- julian-fashion.com/en-US/policy/condshp / spinnakerboutique.com/en-US/policy/condret
- faq.giglio.com/hc/en-us/articles/15269322177041 / thegoods.jp
- tizianafausti.com/us_en/shipment / monnierparis.com/pages/delivery / baltini.com/pages/orders-and-shipping-1
- akamai.com/x-failover/resources/customer-story/luisa-via-roma.html / fashion.spider.jp
- mytheresa.com/us/en/customer-care/shipping / mytheresa.com/at/en/terms-conditions
- farfetch.com/orders-and-shipping/ / crawlbase.com/blog/how-to-scrape-retail-data-from-farfetch/
- medium.com/ssense-tech/fighting-bots-part-i-6f856521ac34 / enlyft.com/tech/company/ynap.com
- livewiremarkets.com/wires/cettire-retail-run-as-tech-2023-08-01 / trustpilot.com/review/www.cettire.com
- endclothing.com/jp/delivery / hbx.com/delivery / kith.com/pages/international-orders / slamjam.com/en-us/policies/shipping-policy
- faq.eu.breuninger.com / fashionista.com/2025/12/matches-newly-acquired-by-hulcan
- ec-navi.com/free-market/buyma/ / us-buyer.com/buyma-shiire / webdeki.com/column/3037/ / the-buyers.jp/research-7/
- live-commerce.com/ecommerce-blog/ebay-duty-tax-ddp/ / hi-japan.com/leather-shoes/ / hunade.com (関税・CITES) / koyano-cpa.gr.jp
