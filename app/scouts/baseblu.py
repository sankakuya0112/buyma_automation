"""BaseBlu セール商品スクレイパー（Playwright 使用）"""

import logging
from typing import List

from sqlalchemy.orm import Session

from app.core.config import get_config
from app.scouts.base import BaseScraper
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)


class BaseBluScraper(BaseScraper):
    """
    BaseBlu セール商品スクレイパー。
    Playwright を使用してセール商品一覧 → 詳細ページをクロールし、
    商品情報（品番、説明、複数画像）を抽出して DB に保存する。
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.source_name = "baseblu"
        self.config = get_config()

    def scrape(self) -> List[dict]:
        """
        BaseBlu セール商品をスクレイピングする。

        Returns:
            商品情報 dict のリスト
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("playwright is not installed. Run: pip install playwright && playwright install")
            return []

        products: List[dict] = []

        with sync_playwright() as p:
            launch_kwargs = {"headless": self.config.headless}
            if self.config.chromium_executable_path:
                launch_kwargs["executable_path"] = self.config.chromium_executable_path
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page()

            try:
                logger.info("Navigating to BaseBlu: %s", self.config.baseblu_search_url)
                page.goto(
                    self.config.baseblu_search_url,
                    timeout=self.config.baseblu_timeout * 1000,
                )
                page.wait_for_load_state("networkidle")

                # 商品リンクを収集
                product_links: List[str] = self._collect_product_links(page)
                logger.info("Found %d product links on BaseBlu", len(product_links))

                for idx, product_url in enumerate(product_links):
                    try:
                        detail_page = browser.new_page()
                        detail_page.goto(
                            product_url,
                            timeout=self.config.baseblu_timeout * 1000,
                        )
                        detail_page.wait_for_load_state("networkidle")

                        product_data = self._extract_product_data(detail_page, product_url)
                        products.append(product_data)
                        detail_page.close()

                        logger.info(
                            "[%d/%d] Scraped: %s %s",
                            idx + 1,
                            len(product_links),
                            product_data["brand"],
                            product_data["title"],
                        )
                    except Exception as exc:
                        logger.error("Failed to scrape product %s: %s", product_url, exc)
                        continue

            finally:
                browser.close()

        return products

    def _collect_product_links(self, page) -> List[str]:
        """
        セール一覧ページから商品詳細ページへのリンク URL を収集する。
        """
        links: List[str] = []
        seen: set[str] = set()

        for a_tag in page.locator('a[href*="/products/"]').all():
            href = a_tag.get_attribute("href") or ""
            if not href:
                continue
            if not href.startswith("http"):
                href = "https://www.baseblu.com" + href
            # クエリ・フラグメントを除去
            href = href.split("?")[0].split("#")[0]
            if href not in seen:
                seen.add(href)
                links.append(href)

        return links

    def _extract_product_data(self, page, product_url: str) -> dict:
        """
        詳細ページから商品情報を抽出する。

        BaseBlu は Shopify ベースのため、product.json エンドポイントを優先的に試みる。
        HTML パースをフォールバックとして使用する。
        """
        # Shopify の product.json エンドポイントを試みる
        json_url = product_url.rstrip("/") + ".json"
        try:
            import requests
            resp = requests.get(json_url, timeout=10, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json().get("product", {})
                return self._parse_shopify_json(data, product_url)
        except Exception:
            pass  # JSON 取得失敗 → HTML フォールバック

        return self._parse_from_html(page, product_url)

    def _parse_shopify_json(self, data: dict, product_url: str) -> dict:
        """Shopify JSON API レスポンスをパースする。"""
        variants = data.get("variants", [])

        # 価格抽出（最安バリアント）
        sale_price = 0.0
        for v in variants:
            try:
                price_val = float(v.get("price", "0"))
                if sale_price == 0 or price_val < sale_price:
                    sale_price = price_val
            except (ValueError, TypeError):
                continue

        # サイズ（option1）
        sizes = list({v.get("option1", "") for v in variants if v.get("option1")})

        # 画像
        image_urls = [img.get("src", "") for img in data.get("images", []) if img.get("src")]
        sub_images = [{"url": img.get("src", ""), "alt_text": img.get("alt", "")} for img in data.get("images", [])[1:]]

        # 説明文（HTML タグ除去）
        body_html = data.get("body_html", "") or ""
        try:
            from bs4 import BeautifulSoup
            description_en = BeautifulSoup(body_html, "lxml").get_text(separator=" ", strip=True)
        except Exception:
            description_en = body_html

        # カラー（options から抽出）
        color = ""
        for opt in data.get("options", []):
            if (opt.get("name") or "").lower() in ("color", "colour", "colore"):
                values = opt.get("values", [])
                color = ", ".join(values)
                break

        return {
            "product_url": product_url,
            "brand": normalize_text(data.get("vendor", "")),
            "title": normalize_text(data.get("title", "")),
            "sku": normalize_text(data.get("handle", "")),
            "color": normalize_text(color),
            "category": normalize_text(data.get("product_type", "")),
            "source_price": sale_price,
            "currency": "EUR",
            "shipping_cost": 0.0,
            "image_urls": image_urls,
            "sub_images": sub_images,
            "description_en": description_en,
            "stock_status": "in_stock",
        }

    def _parse_from_html(self, page, product_url: str) -> dict:
        """Playwright ページオブジェクトから商品情報を HTML パースで抽出する（フォールバック）。"""

        def _safe_text(selector: str) -> str:
            try:
                elem = page.locator(selector).first
                return normalize_text(elem.inner_text() or "")
            except Exception:
                return ""

        def _safe_attr(selector: str, attr: str) -> str:
            try:
                elem = page.locator(selector).first
                return elem.get_attribute(attr) or ""
            except Exception:
                return ""

        brand = _safe_text('[class*="vendor"]') or _safe_text('[class*="brand"]')
        title = _safe_text("h1")
        sku = _safe_text('[class*="sku"]') or _safe_text('[class*="reference"]')
        color = _safe_text('[class*="color"]') or _safe_text('[class*="colour"]')

        # 価格
        price_text = _safe_text('[class*="price"]')
        try:
            price = float(
                price_text.replace("€", "").replace(",", ".").replace(" ", "").strip()
            )
        except (ValueError, AttributeError):
            price = 0.0

        # 画像
        main_src = _safe_attr('[class*="product"] img', "src")
        image_urls = [main_src] if main_src else []

        description_en = _safe_text('[class*="description"]')

        return {
            "product_url": product_url,
            "brand": brand,
            "title": title,
            "sku": sku,
            "color": color,
            "category": "",
            "source_price": price,
            "currency": "EUR",
            "shipping_cost": 0.0,
            "image_urls": image_urls,
            "sub_images": [],
            "description_en": description_en,
            "stock_status": "in_stock",
        }
