"""baseblu.comセール商品スクレイピング"""

import logging
import time

import requests
from bs4 import BeautifulSoup

from config import BASEBLU_SALE_URL

logger = logging.getLogger(__name__)


class BasebluScraper:
    """baseblu.comからセール商品情報を抽出するスクレイパー"""

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

    def fetch_sale_page(self, url: str | None = None, page: int = 1) -> BeautifulSoup:
        """セールページのHTMLを取得してパースする"""
        target_url = url or BASEBLU_SALE_URL
        if page > 1:
            target_url = f"{target_url}?page={page}"

        logger.info("Fetching: %s", target_url)
        response = self.session.get(target_url, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def extract_product_links(self, soup: BeautifulSoup) -> list[str]:
        """商品詳細ページへのリンクを抽出する

        注意: セレクタはbaseblu.comの実際のHTML構造に合わせて調整が必要です。
        """
        links = []
        # TODO: baseblu.comの実際のHTML構造に合わせてセレクタを調整
        product_cards = soup.select("a.product-card, a.product-link")
        for card in product_cards:
            href = card.get("href", "")
            if href:
                links.append(href if href.startswith("http") else f"https://www.baseblu.com{href}")
        logger.info("Found %d product links", len(links))
        return links

    def extract_product_detail(self, product_url: str) -> dict:
        """商品詳細ページから情報を抽出する

        注意: セレクタはbaseblu.comの実際のHTML構造に合わせて調整が必要です。
        """
        logger.info("Fetching product detail: %s", product_url)
        response = self.session.get(product_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        # TODO: baseblu.comの実際のHTML構造に合わせてセレクタを調整
        product = {
            "url": product_url,
            "brand": self._extract_text(soup, ".brand-name, .designer-name"),
            "name": self._extract_text(soup, "h1.product-name, h1.product-title"),
            "original_price_eur": self._extract_text(soup, ".original-price, .price-was"),
            "sale_price_eur": self._extract_text(soup, ".sale-price, .price-now"),
            "description": self._extract_text(soup, ".product-description, .description"),
            "color": self._extract_text(soup, ".color-name, .product-color"),
            "sizes": self._extract_sizes(soup),
            "images": self._extract_images(soup),
            "category": self._extract_text(soup, ".breadcrumb li:last-child, .category-name"),
        }
        return product

    def scrape_sale_products(
        self, max_pages: int = 5, delay: float = 2.0
    ) -> list[dict]:
        """セール商品を一括スクレイピングする"""
        all_products = []
        for page in range(1, max_pages + 1):
            try:
                soup = self.fetch_sale_page(page=page)
                links = self.extract_product_links(soup)
                if not links:
                    logger.info("No more products found at page %d", page)
                    break

                for link in links:
                    try:
                        product = self.extract_product_detail(link)
                        all_products.append(product)
                        time.sleep(delay)
                    except Exception:
                        logger.exception("Failed to scrape product: %s", link)

            except Exception:
                logger.exception("Failed to fetch page %d", page)

        logger.info("Total products scraped: %d", len(all_products))
        return all_products

    @staticmethod
    def _extract_text(soup: BeautifulSoup, selector: str) -> str:
        """CSSセレクタでテキストを抽出する"""
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else ""

    @staticmethod
    def _extract_sizes(soup: BeautifulSoup) -> list[str]:
        """サイズ情報を抽出する"""
        sizes = []
        # TODO: 実際のHTML構造に合わせて調整
        size_elements = soup.select(".size-option, .size-item")
        for elem in size_elements:
            size_text = elem.get_text(strip=True)
            if size_text:
                sizes.append(size_text)
        return sizes

    @staticmethod
    def _extract_images(soup: BeautifulSoup) -> list[str]:
        """商品画像URLを抽出する"""
        images = []
        # TODO: 実際のHTML構造に合わせて調整
        img_elements = soup.select(".product-image img, .gallery img")
        for img in img_elements:
            src = img.get("src") or img.get("data-src", "")
            if src:
                images.append(src)
        return images
