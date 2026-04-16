# PHASE5: Scout 拡張（新規仕入れ先サイト統合）

## 概要

PHASE1 で構築した `BaseScraper` 抽象基底クラスを活用して、新規の仕入れ先サイトを順次追加します。

**実装順序（優先度順）**:
1. YOOX (イタリア ファッションディスカウント)
2. SSENSE (カナダ ハイエンド)
3. Mytheresa (ドイツ ハイエンド)
4. 以降、需要に応じて追加

**完了条件**: 3つ以上の仕入れ先スクレイパーが実装され、`scripts/run_pipeline.py` で複数サイトからの出品が可能なこと。

---

## タスク5-1: YOOX スクレイパー（app/scouts/yoox.py）

### サイト情報

- **URL**: https://www.yoox.com
- **特性**: イタリア発、セール品が豊富、品番は商品ページのSKU欄に記載
- **言語**: 英語
- **通貨**: EUR

### 実装内容

```python
# app/scouts/yoox.py

import logging
from typing import List
from playwright.sync_api import sync_playwright, Page
from sqlalchemy.orm import Session
from app.scouts.base import BaseScraper
from app.core.config import get_config
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)

class YOOXScraper(BaseScraper):
    """
    YOOX セール商品スクレイパー。
    イタリアのファッションディスカウントサイト。
    """
    
    def __init__(self, session: Session):
        super().__init__(session)
        self.source_name = "yoox"
        self.config = get_config()
    
    def scrape(self) -> List[dict]:
        """
        YOOX の セール商品をスクレイピング。
        
        スクレイピング対象：
        - https://www.yoox.com/JP/sale (セールページ)
        - 各商品詳細ページで SKU、説明、複数画像を取得
        """
        products = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                # YOOX セールページへアクセス
                logger.info("Accessing YOOX sale page...")
                page.goto("https://www.yoox.com/JP/sale", timeout=self.config.timeout_seconds * 1000)
                page.wait_for_load_state("networkidle")
                
                # ページネーション処理
                # YOOX は無限スクロールまたはページング
                for page_num in range(1, 11):  # 最大10ページ
                    logger.info(f"Scraping YOOX page {page_num}...")
                    
                    # 商品リンクを取得
                    product_links = page.locator("[data-sku]").all()
                    if not product_links:
                        logger.info("No more products found")
                        break
                    
                    for idx, link in enumerate(product_links):
                        try:
                            product_url = link.get_attribute("href") or ""
                            if not product_url.startswith("http"):
                                product_url = "https://www.yoox.com" + product_url
                            
                            # 詳細ページを開く
                            detail_page = browser.new_page()
                            detail_page.goto(product_url, timeout=self.config.timeout_seconds * 1000)
                            detail_page.wait_for_load_state("networkidle")
                            
                            # 商品情報を抽出
                            product_data = self._extract_product_data(detail_page, product_url)
                            if product_data:
                                products.append(product_data)
                                logger.info(
                                    f"[{len(products)}] {product_data['brand']} "
                                    f"{product_data['title']} - €{product_data['source_price']}"
                                )
                            
                            detail_page.close()
                        except Exception as e:
                            logger.error(f"Failed to scrape product {idx}: {e}")
                            continue
                    
                    # 次ページへ
                    try:
                        next_button = page.locator("a[rel='next']")
                        if next_button.is_visible():
                            next_button.click()
                            page.wait_for_load_state("networkidle")
                        else:
                            break
                    except Exception:
                        break
            finally:
                browser.close()
        
        return products
    
    def _extract_product_data(self, page: Page, product_url: str) -> dict:
        """
        YOOX 商品詳細ページから情報を抽出。
        """
        try:
            # ブランド
            brand = page.locator("[data-brand]").inner_text() or ""
            
            # 商品名
            title = page.locator("h1[data-product-name]").inner_text() or ""
            
            # SKU（品番）
            sku = page.locator("[data-sku]").get_attribute("data-sku") or ""
            
            # 色
            color = page.locator("[data-color-name]").inner_text() or ""
            
            # 価格（元値と割引後の両方を取得）
            price_text = page.locator("[data-price-sale]").inner_text() or page.locator("[data-price]").inner_text()
            if not price_text:
                return None
            
            # "€99.99" → 99.99
            price = float(price_text.replace("€", "").replace(",", ".").strip())
            
            # カテゴリ
            category = ""
            breadcrumb = page.locator("[data-breadcrumb-item]").all()
            if len(breadcrumb) > 1:
                category = breadcrumb[-2].inner_text()
            
            # メイン画像
            main_image = page.locator("[data-main-image]").get_attribute("src") or ""
            
            # サブ画像
            sub_images_elements = page.locator("[data-gallery-item] img").all()
            sub_images = [
                {
                    "url": img.get_attribute("src"),
                    "alt_text": img.get_attribute("alt") or ""
                }
                for img in sub_images_elements
                if img.get_attribute("src")
            ]
            
            # 説明
            description_en = page.locator("[data-description]").inner_text() or ""
            
            # 在庫確認
            in_stock_text = page.locator("[data-stock]").inner_text() or "In Stock"
            stock_status = "in_stock" if "in stock" in in_stock_text.lower() else "limited"
            
            return {
                'product_url': product_url,
                'brand': normalize_text(brand),
                'title': normalize_text(title),
                'sku': normalize_text(sku),
                'color': normalize_text(color),
                'category': normalize_text(category),
                'source_price': price,
                'currency': 'EUR',
                'shipping_cost': 0.0,  # YOOX の送料ポリシーを別途確認
                'image_urls': [main_image] if main_image else [],
                'sub_images': sub_images,
                'description_en': description_en,
                'stock_status': stock_status,
            }
        except Exception as e:
            logger.error(f"Failed to extract product data: {e}")
            return None
```

### 納品物チェックリスト

- [ ] `app/scouts/yoox.py` が作成されている
- [ ] YOOXScraper が BaseScraper を継承
- [ ] scrape() で YOOX セールページをクロール
- [ ] _extract_product_data() で SKU、説明、複数画像を抽出
- [ ] ページネーション処理が実装

---

## タスク5-2: SSENSE スクレイパー（app/scouts/ssense.py）

### サイト情報

- **URL**: https://www.ssense.com
- **特性**: カナダ発、ハイエンドブランド充実、APIベース推奨
- **言語**: 英語
- **通貨**: USD、CAD

### 実装内容

```python
# app/scouts/ssense.py

import logging
from typing import List
import requests
import json
from sqlalchemy.orm import Session
from app.scouts.base import BaseScraper
from app.utils.text import normalize_text
from app.utils.retry import retry

logger = logging.getLogger(__name__)

class SSENSEScraper(BaseScraper):
    """
    SSENSE セール商品スクレイパー。
    API を活用した高速スクレイピング。
    
    SSENSE は GraphQL API を提供しており、Playwright 不要。
    """
    
    def __init__(self, session: Session):
        super().__init__(session)
        self.source_name = "ssense"
        self.base_url = "https://www.ssense.com/api"
    
    def scrape(self) -> List[dict]:
        """
        SSENSE GraphQL API からセール商品を取得。
        """
        products = []
        
        try:
            # GraphQL クエリ
            query = """
            query {
                products(filters: {onSale: true}, limit: 100) {
                    nodes {
                        id
                        name
                        brand {
                            name
                        }
                        color
                        sku
                        price {
                            sale
                            original
                            currency
                        }
                        images {
                            url
                            alt
                        }
                        description
                        inStock
                    }
                }
            }
            """
            
            response = self._query_api(query)
            if not response:
                return products
            
            product_nodes = response.get("data", {}).get("products", {}).get("nodes", [])
            
            for product_data in product_nodes:
                try:
                    product = self._transform_product(product_data)
                    products.append(product)
                    logger.info(f"Scraped: {product['brand']} {product['title']}")
                except Exception as e:
                    logger.warning(f"Failed to transform product: {e}")
                    continue
            
            logger.info(f"Scraped {len(products)} products from SSENSE")
            return products
        except Exception as e:
            logger.error(f"SSENSE scraping failed: {e}")
            return products
    
    @retry(max_retries=3, delay=2)
    def _query_api(self, query: str) -> dict:
        """
        GraphQL API にクエリを実行。
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; BUYMAAutomation/1.0)",
        }
        
        payload = {
            "query": query,
        }
        
        response = requests.post(
            f"{self.base_url}/graphql",
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    
    def _transform_product(self, api_data: dict) -> dict:
        """
        API レスポンスをスクレイパーの標準形式に変換。
        """
        images = api_data.get("images", [])
        
        return {
            'product_url': f"https://www.ssense.com/en-us/men/product/{api_data['id']}",
            'brand': normalize_text(api_data.get("brand", {}).get("name", "")),
            'title': normalize_text(api_data.get("name", "")),
            'sku': normalize_text(api_data.get("sku", "")),
            'color': normalize_text(api_data.get("color", "")),
            'category': "",  # API に含まれない場合は空
            'source_price': api_data.get("price", {}).get("sale", 0),
            'currency': api_data.get("price", {}).get("currency", "USD"),
            'shipping_cost': 0.0,
            'image_urls': [img.get("url") for img in images[:1]] if images else [],
            'sub_images': [
                {"url": img.get("url"), "alt_text": img.get("alt", "")}
                for img in images[1:]
            ],
            'description_en': api_data.get("description", ""),
            'stock_status': "in_stock" if api_data.get("inStock") else "out_of_stock",
        }
```

### 納品物チェックリスト

- [ ] `app/scouts/ssense.py` が作成されている
- [ ] SSENSEScraper が GraphQL API を活用
- [ ] scrape() で API からセール商品を取得
- [ ] _query_api() で GraphQL クエリを実行（リトライ付き）
- [ ] _transform_product() で API データを標準形式に変換

---

## タスク5-3: Mytheresa スクレイパー（app/scouts/mytheresa.py）

### サイト情報

- **URL**: https://www.mytheresa.com
- **特性**: ドイツ発、ハイエンドブランド、セール品充実
- **言語**: 英語
- **通貨**: EUR

### 実装内容

```python
# app/scouts/mytheresa.py

import logging
from typing import List
from playwright.sync_api import sync_playwright, Page
from sqlalchemy.orm import Session
from app.scouts.base import BaseScraper
from app.core.config import get_config
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)

class MytheresaScraper(BaseScraper):
    """
    Mytheresa セール商品スクレイパー。
    ドイツのハイエンドオンラインストア。
    """
    
    def __init__(self, session: Session):
        super().__init__(session)
        self.source_name = "mytheresa"
        self.config = get_config()
    
    def scrape(self) -> List[dict]:
        """
        Mytheresa のセール商品をスクレイピング。
        """
        products = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.config.headless)
            page = browser.new_page()
            
            try:
                logger.info("Accessing Mytheresa sale page...")
                page.goto("https://www.mytheresa.com/en-de/sale", timeout=self.config.timeout_seconds * 1000)
                page.wait_for_load_state("networkidle")
                
                # 商品リストを取得
                product_containers = page.locator("[data-product-container]").all()
                logger.info(f"Found {len(product_containers)} products on Mytheresa")
                
                for idx, container in enumerate(product_containers):
                    try:
                        product_url = container.locator("a").first.get_attribute("href")
                        if not product_url.startswith("http"):
                            product_url = "https://www.mytheresa.com" + product_url
                        
                        # 詳細ページを開く
                        detail_page = browser.new_page()
                        detail_page.goto(product_url, timeout=self.config.timeout_seconds * 1000)
                        detail_page.wait_for_load_state("networkidle")
                        
                        product_data = self._extract_product_data(detail_page, product_url)
                        if product_data:
                            products.append(product_data)
                            logger.info(f"[{idx + 1}] {product_data['brand']} {product_data['title']}")
                        
                        detail_page.close()
                    except Exception as e:
                        logger.error(f"Failed to scrape product {idx}: {e}")
                        continue
            finally:
                browser.close()
        
        return products
    
    def _extract_product_data(self, page: Page, product_url: str) -> dict:
        """
        Mytheresa 商品詳細ページから情報を抽出。
        """
        try:
            brand = page.locator("[data-brand-name]").inner_text() or ""
            title = page.locator("h1[data-product-name]").inner_text() or ""
            sku = page.locator("[data-sku]").inner_text() or ""
            color = page.locator("[data-color]").inner_text() or ""
            
            price_text = page.locator("[data-sale-price]").inner_text() or page.locator("[data-price]").inner_text()
            if not price_text:
                return None
            
            price = float(price_text.replace("€", "").replace(",", ".").strip())
            
            main_image = page.locator("[data-main-image] img").get_attribute("src") or ""
            
            sub_images_elements = page.locator("[data-gallery] img").all()
            sub_images = [
                {"url": img.get_attribute("src"), "alt_text": img.get_attribute("alt") or ""}
                for img in sub_images_elements
                if img.get_attribute("src")
            ]
            
            description_en = page.locator("[data-product-description]").inner_text() or ""
            
            return {
                'product_url': product_url,
                'brand': normalize_text(brand),
                'title': normalize_text(title),
                'sku': normalize_text(sku),
                'color': normalize_text(color),
                'category': "",
                'source_price': price,
                'currency': 'EUR',
                'shipping_cost': 0.0,
                'image_urls': [main_image] if main_image else [],
                'sub_images': sub_images,
                'description_en': description_en,
                'stock_status': "in_stock",
            }
        except Exception as e:
            logger.error(f"Failed to extract product data: {e}")
            return None
```

### 納品物チェックリスト

- [ ] `app/scouts/mytheresa.py` が作成されている
- [ ] MytheresaScraper が BaseScraper を継承
- [ ] scrape() で Mytheresa セールページをクロール
- [ ] _extract_product_data() で情報を抽出

---

## タスク5-4: マルチスクレイパー統合（scripts/run_scouts.py）

### 実施内容

複数のスクレイパーを統合実行するスクリプト。

```python
# scripts/run_scouts.py

#!/usr/bin/env python3
"""
全スクレイパーを実行。
複数の仕入れ先から商品を取得。

Usage:
    python3 scripts/run_scouts.py [OPTIONS]

Options:
    --source baseblu,yoox,ssense,mytheresa  : 実行対象スクレイパー（カンマ区切り）
    --all                                    : 全スクレイパーを実行
"""

import sys
import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_config
from app.core.logger import setup_logger
from app.core.models import Base
from app.scouts.baseblu import BaseBluScraper
from app.scouts.yoox import YOOXScraper
from app.scouts.ssense import SSENSEScraper
from app.scouts.mytheresa import MytheresaScraper

logger = setup_logger("run_scouts")

SCRAPERS = {
    'baseblu': BaseBluScraper,
    'yoox': YOOXScraper,
    'ssense': SSENSEScraper,
    'mytheresa': MytheresaScraper,
}

def main():
    parser = argparse.ArgumentParser(description="Multi-source product scraping")
    parser.add_argument("--source", default="baseblu", help="Scrapers to run (comma-separated)")
    parser.add_argument("--all", action="store_true", help="Run all scrapers")
    
    args = parser.parse_args()
    
    # DB 初期化
    config = get_config()
    engine = create_engine(f"sqlite:///{config.db_path}")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    
    try:
        # 実行対象スクレイパーを決定
        if args.all:
            sources = list(SCRAPERS.keys())
        else:
            sources = [s.strip() for s in args.source.split(",")]
        
        logger.info(f"Running scrapers: {sources}")
        
        total_products = 0
        
        for source in sources:
            if source not in SCRAPERS:
                logger.error(f"Unknown scraper: {source}")
                continue
            
            logger.info(f"=== Starting {source} ===")
            
            try:
                scraper_class = SCRAPERS[source]
                scraper = scraper_class(session)
                products = scraper.run()
                total_products += len(products)
                
                logger.info(f"Completed {source}: {len(products)} products")
            except Exception as e:
                logger.error(f"Failed to run {source}: {e}")
        
        logger.info(f"Total products scraped: {total_products}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
```

### 実行例

```bash
# BaseBlu のみ実行
python3 scripts/run_scouts.py

# 複数スクレイパーを実行
python3 scripts/run_scouts.py --source baseblu,yoox,ssense,mytheresa

# 全スクレイパーを実行
python3 scripts/run_scouts.py --all
```

### 納品物チェックリスト

- [ ] `scripts/run_scouts.py` が作成されている
- [ ] 複数スクレイパーを統合実行可能
- [ ] --source, --all オプションが実装
- [ ] 各スクレイパーの結果が集計される

---

## 設定管理（data/sources.json）

### 実施内容

各スクレイパーの設定を一元管理するファイル。

```json
{
  "sources": [
    {
      "name": "baseblu",
      "url": "https://www.baseblu.com",
      "enabled": true,
      "priority": 1,
      "search_url": "https://www.baseblu.com/en/sales",
      "currency": "EUR",
      "country": "IT"
    },
    {
      "name": "yoox",
      "url": "https://www.yoox.com",
      "enabled": true,
      "priority": 2,
      "search_url": "https://www.yoox.com/JP/sale",
      "currency": "EUR",
      "country": "IT"
    },
    {
      "name": "ssense",
      "url": "https://www.ssense.com",
      "enabled": true,
      "priority": 3,
      "api_endpoint": "https://www.ssense.com/api/graphql",
      "currency": "USD",
      "country": "CA"
    },
    {
      "name": "mytheresa",
      "url": "https://www.mytheresa.com",
      "enabled": true,
      "priority": 4,
      "search_url": "https://www.mytheresa.com/en-de/sale",
      "currency": "EUR",
      "country": "DE"
    }
  ]
}
```

### 用途

- スクレイパーの有効/無効切り替え
- 優先度管理（複数サイトで同一商品の場合）
- 通貨・国ごとの設定一元管理
- 拡張時の参照仕様書

---

## ディレクトリ構成の更新

PHASE5 完了後：

```
app/
├── scouts/
│   ├── __init__.py
│   ├── base.py         ← 抽象基底クラス
│   ├── baseblu.py      ← BaseBlu スクレイパー
│   ├── yoox.py         ← YOOX スクレイパー
│   ├── ssense.py       ← SSENSE スクレイパー
│   └── mytheresa.py    ← Mytheresa スクレイパー
├── order_desk/
├── ranker/
├── guards/
├── core/
├── listing/
└── utils/

scripts/
├── run_pipeline.py     ← PHASE1
├── run_guard.py        ← PHASE2
├── run_ranker.py       ← PHASE3
├── run_order_desk.py   ← PHASE4
└── run_scouts.py       ← PHASE5

data/
├── categories.json
├── brands.json
├── brand_scores.json
├── category_scores.json
└── sources.json        ← 新規
```

---

## 拡張時の手順書

新しい仕入れ先を追加する場合：

1. **app/scouts/ に新規スクレイパー作成**
   ```python
   # app/scouts/new_source.py
   from app.scouts.base import BaseScraper
   
   class NewSourceScraper(BaseScraper):
       def __init__(self, session):
           super().__init__(session)
           self.source_name = "new_source"
       
       def scrape(self) -> List[dict]:
           # スクレイピング実装
           pass
   ```

2. **scripts/run_scouts.py に追加**
   ```python
   from app.scouts.new_source import NewSourceScraper
   
   SCRAPERS = {
       ...
       'new_source': NewSourceScraper,
   }
   ```

3. **data/sources.json に設定追加**
   ```json
   {
     "name": "new_source",
     "url": "https://...",
     ...
   }
   ```

4. **テスト実行**
   ```bash
   python3 scripts/run_scouts.py --source new_source
   ```

---

## 最終チェックリスト（PHASE5 完了）

- [ ] YOOX, SSENSE, Mytheresa スクレイパーが実装
- [ ] すべてのスクレイパーが BaseScraper を継承
- [ ] `scripts/run_scouts.py` で複数サイトからの実行が可能
- [ ] `data/sources.json` で全スクレイパーの設定を一元管理
- [ ] 新規スクレイパー追加が容易な設計になっている

