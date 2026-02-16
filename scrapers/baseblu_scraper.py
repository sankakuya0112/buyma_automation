"""baseblu.comセール商品スクレイピング

baseblu.comはShopifyベースのストアのため、
Shopify JSON API（/products.json）を主要な取得手段として使用し、
HTMLパースをフォールバックとして併用する。
"""

import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from config import (
    BASEBLU_BASE_URL,
    BASEBLU_LOCALE,
    BASEBLU_PRODUCTS_PER_PAGE,
    BASEBLU_SALE_COLLECTIONS,
)

logger = logging.getLogger(__name__)

# リクエスト間隔（秒）
DEFAULT_DELAY = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


class BasebluScraper:
    """baseblu.comからセール商品情報を抽出するスクレイパー

    Shopify JSON API を優先的に使用し、失敗時はHTMLパースにフォールバックする。
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.base_url = BASEBLU_BASE_URL
        self.locale = BASEBLU_LOCALE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_sale_products(
        self,
        max_pages: int = 5,
        delay: float = DEFAULT_DELAY,
        collections: list[str] | None = None,
    ) -> list[dict]:
        """セール商品を一括スクレイピングする

        Args:
            max_pages: コレクションごとの最大取得ページ数
            delay: リクエスト間の待機秒数
            collections: 対象コレクション名リスト（省略時はconfig値）

        Returns:
            商品情報dictのリスト
        """
        target_collections = collections or BASEBLU_SALE_COLLECTIONS
        all_products: list[dict] = []
        seen_handles: set[str] = set()

        for collection in target_collections:
            logger.info("Scraping collection: %s", collection)
            products = self._scrape_collection(
                collection, max_pages=max_pages, delay=delay
            )

            # 重複排除（複数コレクション間で同一商品が存在しうる）
            for product in products:
                handle = product.get("handle", product.get("url", ""))
                if handle and handle not in seen_handles:
                    seen_handles.add(handle)
                    all_products.append(product)

        logger.info(
            "Total unique products scraped: %d (from %d collections)",
            len(all_products),
            len(target_collections),
        )
        return all_products

    # ------------------------------------------------------------------
    # Collection scraping
    # ------------------------------------------------------------------

    def _scrape_collection(
        self, collection: str, max_pages: int, delay: float
    ) -> list[dict]:
        """指定コレクションの全商品を取得する"""
        # まずJSON APIを試行
        products = self._scrape_collection_json(collection, max_pages, delay)
        if products:
            return products

        # JSON API失敗時はHTMLフォールバック
        logger.info("JSON API unavailable, falling back to HTML for: %s", collection)
        return self._scrape_collection_html(collection, max_pages, delay)

    # ------------------------------------------------------------------
    # Shopify JSON API
    # ------------------------------------------------------------------

    def _scrape_collection_json(
        self, collection: str, max_pages: int, delay: float
    ) -> list[dict]:
        """Shopify JSON APIでコレクション商品を取得する"""
        products: list[dict] = []

        for page in range(1, max_pages + 1):
            url = (
                f"{self.base_url}/{self.locale}/collections/{collection}"
                f"/products.json?page={page}&limit={BASEBLU_PRODUCTS_PER_PAGE}"
            )
            data = self._fetch_json(url)
            if data is None:
                return []  # JSON API自体が使えない

            raw_products = data.get("products", [])
            if not raw_products:
                logger.info(
                    "No more products in JSON at page %d for %s", page, collection
                )
                break

            for raw in raw_products:
                product = self._parse_shopify_product(raw, collection)
                if product and self._is_on_sale(product):
                    products.append(product)

            logger.info(
                "JSON page %d: fetched %d products for %s",
                page,
                len(raw_products),
                collection,
            )
            time.sleep(delay)

        return products

    def _parse_shopify_product(self, raw: dict, collection: str) -> dict | None:
        """Shopify JSON APIのproductオブジェクトを内部形式に変換する"""
        try:
            handle = raw.get("handle", "")
            product_url = f"{self.base_url}/{self.locale}/products/{handle}"

            # バリアント情報から価格・サイズを抽出
            variants = raw.get("variants", [])
            original_price, sale_price = self._extract_prices_from_variants(variants)
            sizes = self._extract_sizes_from_variants(variants)
            available_sizes = self._extract_available_sizes(variants)

            # 画像URL
            images = [img.get("src", "") for img in raw.get("images", []) if img.get("src")]

            # 説明文（HTMLタグ除去）
            body_html = raw.get("body_html", "") or ""
            description = self._strip_html(body_html)

            # カラー抽出（optionsまたはvariants）
            color = self._extract_color(raw)

            # カテゴリ（product_type）
            category = raw.get("product_type", "")

            # タグ
            tags = raw.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]

            return {
                "handle": handle,
                "url": product_url,
                "brand": raw.get("vendor", ""),
                "name": raw.get("title", ""),
                "original_price_eur": original_price,
                "sale_price_eur": sale_price,
                "discount_rate": self._calc_discount_rate(original_price, sale_price),
                "description": description,
                "color": color,
                "sizes": ", ".join(sizes),
                "available_sizes": ", ".join(available_sizes),
                "images": ", ".join(images),
                "category": category,
                "tags": ", ".join(tags) if tags else "",
                "collection": collection,
            }
        except Exception:
            logger.exception("Failed to parse product: %s", raw.get("handle", "?"))
            return None

    @staticmethod
    def _extract_prices_from_variants(variants: list[dict]) -> tuple[str, str]:
        """バリアントから元値・セール価格を抽出する

        compare_at_price が元値、price がセール価格。
        複数バリアントがある場合は最安のセール価格を採用。
        """
        original_price = ""
        sale_price = ""
        min_sale = float("inf")

        for v in variants:
            price_str = v.get("price", "0")
            compare_str = v.get("compare_at_price") or ""

            try:
                price_val = float(price_str)
            except (ValueError, TypeError):
                continue

            if price_val < min_sale:
                min_sale = price_val
                sale_price = price_str
                original_price = compare_str if compare_str else price_str

        return original_price, sale_price

    @staticmethod
    def _extract_sizes_from_variants(variants: list[dict]) -> list[str]:
        """バリアントから全サイズを抽出する"""
        sizes: list[str] = []
        seen: set[str] = set()
        for v in variants:
            # Shopifyのoption1は通常サイズ
            size = v.get("option1", "")
            if size and size not in seen:
                seen.add(size)
                sizes.append(size)
        return sizes

    @staticmethod
    def _extract_available_sizes(variants: list[dict]) -> list[str]:
        """在庫ありのサイズのみを抽出する"""
        sizes: list[str] = []
        seen: set[str] = set()
        for v in variants:
            if v.get("available", False):
                size = v.get("option1", "")
                if size and size not in seen:
                    seen.add(size)
                    sizes.append(size)
        return sizes

    @staticmethod
    def _extract_color(raw: dict) -> str:
        """商品のカラー情報を抽出する"""
        # optionsから"Color"を探す
        for option in raw.get("options", []):
            name = (option.get("name") or "").lower()
            if name in ("color", "colour", "colore"):
                values = option.get("values", [])
                return ", ".join(values) if values else ""

        # バリアントのoption2をフォールバックで使用
        colors: list[str] = []
        seen: set[str] = set()
        for v in raw.get("variants", []):
            color = v.get("option2", "")
            if color and color not in seen:
                seen.add(color)
                colors.append(color)
        return ", ".join(colors)

    @staticmethod
    def _is_on_sale(product: dict) -> bool:
        """セール価格が設定されている商品かを判定する"""
        orig = product.get("original_price_eur", "")
        sale = product.get("sale_price_eur", "")
        if not orig or not sale:
            return True  # 価格情報がない場合は含める
        try:
            return float(sale) < float(orig)
        except (ValueError, TypeError):
            return True

    @staticmethod
    def _calc_discount_rate(original: str, sale: str) -> str:
        """割引率を計算する"""
        try:
            orig_val = float(original)
            sale_val = float(sale)
            if orig_val > 0:
                rate = (1 - sale_val / orig_val) * 100
                return f"{rate:.0f}%"
        except (ValueError, TypeError):
            pass
        return ""

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    def _scrape_collection_html(
        self, collection: str, max_pages: int, delay: float
    ) -> list[dict]:
        """HTMLページをパースしてコレクション商品を取得する（フォールバック）"""
        products: list[dict] = []

        for page in range(1, max_pages + 1):
            url = (
                f"{self.base_url}/{self.locale}/collections/{collection}"
                f"?page={page}"
            )
            soup = self._fetch_html(url)
            if soup is None:
                break

            links = self._extract_product_links_html(soup)
            if not links:
                logger.info("No more products in HTML at page %d for %s", page, collection)
                break

            logger.info(
                "HTML page %d: found %d product links for %s",
                page,
                len(links),
                collection,
            )

            for link in links:
                try:
                    product = self._fetch_product_detail(link, collection)
                    if product:
                        products.append(product)
                    time.sleep(delay)
                except Exception:
                    logger.exception("Failed to scrape product: %s", link)

        return products

    def _extract_product_links_html(self, soup: BeautifulSoup) -> list[str]:
        """一覧ページから商品詳細へのリンクを抽出する"""
        links: list[str] = []
        seen: set[str] = set()

        # Shopifyテーマで一般的なセレクタパターン
        selectors = [
            'a[href*="/products/"]',
        ]

        for selector in selectors:
            for a_tag in soup.select(selector):
                href = a_tag.get("href", "")
                if not href or "/products/" not in href:
                    continue

                # フルURLに正規化
                if href.startswith("/"):
                    href = f"{self.base_url}{href}"

                # 重複・アンカー除去
                href = href.split("?")[0].split("#")[0]
                if href not in seen:
                    seen.add(href)
                    links.append(href)

        return links

    def _fetch_product_detail(self, product_url: str, collection: str) -> dict | None:
        """商品詳細ページから情報を抽出する（JSON埋め込みを優先）"""
        # まずproduct.jsonを試行
        json_url = product_url.rstrip("/") + ".json"
        data = self._fetch_json(json_url)
        if data and "product" in data:
            return self._parse_shopify_product(data["product"], collection)

        # HTMLフォールバック
        soup = self._fetch_html(product_url)
        if soup is None:
            return None

        return self._parse_product_html(soup, product_url, collection)

    def _parse_product_html(
        self, soup: BeautifulSoup, url: str, collection: str
    ) -> dict | None:
        """HTMLから商品情報を抽出する"""
        try:
            # Shopifyページに埋め込まれたJSON-LDを探す
            product = self._extract_from_jsonld(soup, url, collection)
            if product:
                return product

            # ShopifyのmetaタグやScript埋め込みから抽出を試みる
            product = self._extract_from_shopify_meta(soup, url, collection)
            if product:
                return product

            # 最終手段: HTMLタグから直接抽出
            return self._extract_from_html_tags(soup, url, collection)
        except Exception:
            logger.exception("Failed to parse HTML for: %s", url)
            return None

    def _extract_from_jsonld(
        self, soup: BeautifulSoup, url: str, collection: str
    ) -> dict | None:
        """JSON-LD構造化データから商品情報を抽出する"""
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "Product":
                    offers = data.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}

                    return {
                        "handle": url.split("/products/")[-1].split("?")[0] if "/products/" in url else "",
                        "url": url,
                        "brand": data.get("brand", {}).get("name", "") if isinstance(data.get("brand"), dict) else str(data.get("brand", "")),
                        "name": data.get("name", ""),
                        "original_price_eur": "",
                        "sale_price_eur": offers.get("price", ""),
                        "discount_rate": "",
                        "description": data.get("description", ""),
                        "color": "",
                        "sizes": "",
                        "available_sizes": "",
                        "images": data.get("image", ""),
                        "category": "",
                        "tags": "",
                        "collection": collection,
                    }
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _extract_from_shopify_meta(
        self, soup: BeautifulSoup, url: str, collection: str
    ) -> dict | None:
        """Shopifyのmeta/script埋め込みデータから商品情報を抽出する"""
        # Shopifyテーマの多くは window.ShopifyAnalytics.meta にproduct情報を持つ
        for script in soup.find_all("script"):
            text = script.string or ""
            if "var meta" in text or "ShopifyAnalytics" in text:
                # productオブジェクトをJSONとして抽出
                match = re.search(r'"product"\s*:\s*(\{.+?\})\s*[,}]', text)
                if match:
                    try:
                        product_data = json.loads(match.group(1))
                        return {
                            "handle": product_data.get("handle", ""),
                            "url": url,
                            "brand": product_data.get("vendor", ""),
                            "name": product_data.get("title", ""),
                            "original_price_eur": "",
                            "sale_price_eur": str(product_data.get("price", "")),
                            "discount_rate": "",
                            "description": "",
                            "color": "",
                            "sizes": "",
                            "available_sizes": "",
                            "images": "",
                            "category": product_data.get("type", ""),
                            "tags": "",
                            "collection": collection,
                        }
                    except json.JSONDecodeError:
                        continue
        return None

    def _extract_from_html_tags(
        self, soup: BeautifulSoup, url: str, collection: str
    ) -> dict:
        """HTMLタグから直接商品情報を抽出する（最終手段）"""
        # タイトル
        name = ""
        for selector in ["h1", '[class*="product-title"]', '[class*="product-name"]']:
            elem = soup.select_one(selector)
            if elem:
                name = elem.get_text(strip=True)
                break

        # ブランド名
        brand = ""
        for selector in [
            '[class*="vendor"]',
            '[class*="brand"]',
            '[class*="designer"]',
        ]:
            elem = soup.select_one(selector)
            if elem:
                brand = elem.get_text(strip=True)
                break

        # 価格
        prices = self._extract_prices_from_html(soup)

        # 画像
        images: list[str] = []
        for img in soup.select('[class*="product"] img, [class*="gallery"] img'):
            src = img.get("src") or img.get("data-src") or ""
            if src and "cdn.shopify.com" in src:
                images.append(src if src.startswith("http") else f"https:{src}")

        # 説明文
        description = ""
        for selector in [
            '[class*="product-description"]',
            '[class*="description"]',
            ".rte",
        ]:
            elem = soup.select_one(selector)
            if elem:
                description = elem.get_text(strip=True)
                break

        return {
            "handle": url.split("/products/")[-1].split("?")[0] if "/products/" in url else "",
            "url": url,
            "brand": brand,
            "name": name,
            "original_price_eur": prices.get("original", ""),
            "sale_price_eur": prices.get("sale", ""),
            "discount_rate": self._calc_discount_rate(
                prices.get("original", ""), prices.get("sale", "")
            ),
            "description": description,
            "color": "",
            "sizes": "",
            "available_sizes": "",
            "images": ", ".join(images),
            "category": "",
            "tags": "",
            "collection": collection,
        }

    @staticmethod
    def _extract_prices_from_html(soup: BeautifulSoup) -> dict[str, str]:
        """HTMLから元値・セール価格を抽出する"""
        result: dict[str, str] = {"original": "", "sale": ""}

        # Shopifyテーマ共通のクラスパターン
        compare_selectors = [
            '[class*="compare"]',
            '[class*="was"]',
            "s",
            "del",
            '[class*="original"]',
            '[class*="regular"]',
        ]
        sale_selectors = [
            '[class*="sale"]',
            '[class*="now"]',
            '[class*="current"]',
            '[class*="price"] :not(s):not(del)',
        ]

        for selector in compare_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                price = re.sub(r"[^\d.,]", "", text)
                if price:
                    result["original"] = price.replace(",", "")
                    break

        for selector in sale_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    price = re.sub(r"[^\d.,]", "", text)
                    if price:
                        result["sale"] = price.replace(",", "")
                        break
            except Exception:
                continue

        return result

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str) -> dict | None:
        """JSON APIリクエスト（リトライ付き）"""
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug("Fetching JSON: %s (attempt %d)", url, attempt + 1)
                response = self.session.get(
                    url,
                    timeout=30,
                    headers={"Accept": "application/json"},
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code in (404, 403, 401):
                    logger.debug("JSON endpoint not available: %s (%d)", url, response.status_code)
                    return None
                logger.warning(
                    "JSON request returned %d for %s", response.status_code, url
                )
            except requests.exceptions.JSONDecodeError:
                logger.warning("Invalid JSON response from %s", url)
                return None
            except requests.exceptions.RequestException as e:
                logger.warning("Request failed for %s: %s", url, e)

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                logger.debug("Retrying in %.1f seconds...", wait)
                time.sleep(wait)

        return None

    def _fetch_html(self, url: str) -> BeautifulSoup | None:
        """HTMLページ取得（リトライ付き）"""
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug("Fetching HTML: %s (attempt %d)", url, attempt + 1)
                response = self.session.get(url, timeout=30)
                if response.status_code == 200:
                    return BeautifulSoup(response.text, "lxml")
                if response.status_code in (404, 403, 401):
                    logger.warning("Page not accessible: %s (%d)", url, response.status_code)
                    return None
                logger.warning(
                    "HTML request returned %d for %s", response.status_code, url
                )
            except requests.exceptions.RequestException as e:
                logger.warning("Request failed for %s: %s", url, e)

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                logger.debug("Retrying in %.1f seconds...", wait)
                time.sleep(wait)

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_html(html: str) -> str:
        """HTMLタグを除去してプレーンテキストにする"""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)
