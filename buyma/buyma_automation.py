"""BUYMA自動出品処理"""

import logging
import random
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from buyma.buyma_login import BuymaLogin
from config import (
    BUYMA_EXHIBIT_URL,
    LISTING_INTERVAL_MAX,
    LISTING_INTERVAL_MIN,
    SELENIUM_TIMEOUT,
)

logger = logging.getLogger(__name__)


class BuymaAutomation:
    """BUYMA自動出品クラス"""

    def __init__(self):
        self.login_handler = BuymaLogin()
        self.driver = None

    def start(self) -> bool:
        """ブラウザ起動・ログインして出品準備を整える"""
        self.driver = self.login_handler.setup_driver()
        return self.login_handler.login()

    def navigate_to_exhibit(self) -> bool:
        """出品ページに遷移する"""
        if not self.driver:
            logger.error("Driver not initialized")
            return False

        try:
            self.driver.get(BUYMA_EXHIBIT_URL)
            WebDriverWait(self.driver, SELENIUM_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "form"))
            )
            logger.info("Navigated to exhibit page")
            return True
        except Exception:
            logger.exception("Failed to navigate to exhibit page")
            return False

    def fill_product_form(self, product: dict) -> bool:
        """出品フォームに商品情報を入力する

        注意: セレクタはBUYMAの実際のフォーム構造に合わせて調整が必要です。

        Args:
            product: 商品情報の辞書（以下のキーを含む）
                - brand: ブランド名
                - name_ja: 商品名（日本語）
                - description_ja: 商品説明（日本語）
                - price_jpy: 販売価格（日本円）
                - category: カテゴリ
                - color: カラー
                - sizes: サイズリスト
                - images: 画像URLリスト
        """
        if not self.driver:
            logger.error("Driver not initialized")
            return False

        try:
            wait = WebDriverWait(self.driver, SELENIUM_TIMEOUT)

            # TODO: BUYMAの実際のフォーム要素に合わせてセレクタを調整
            # 商品名
            name_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#product_name, input[name='product_name']"))
            )
            name_input.clear()
            name_input.send_keys(product.get("name_ja", ""))

            # 商品コメント（説明文）
            desc_input = self.driver.find_element(
                By.CSS_SELECTOR, "#product_comment, textarea[name='product_comment']"
            )
            desc_input.clear()
            desc_input.send_keys(product.get("description_ja", ""))

            # 販売価格
            price_input = self.driver.find_element(
                By.CSS_SELECTOR, "#product_price, input[name='price']"
            )
            price_input.clear()
            price_input.send_keys(str(product.get("price_jpy", "")))

            logger.info("Product form filled: %s", product.get("name_ja", ""))
            return True

        except Exception:
            logger.exception("Failed to fill product form")
            return False

    def submit_listing(self) -> bool:
        """出品を確定する"""
        if not self.driver:
            return False

        try:
            # TODO: 実際の送信ボタンのセレクタに調整
            submit_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.submit-listing, #btnExhibit"
            )
            submit_btn.click()

            WebDriverWait(self.driver, SELENIUM_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".success-message, .complete"))
            )
            logger.info("Listing submitted successfully")
            return True

        except Exception:
            logger.exception("Failed to submit listing")
            return False

    def list_products(self, products: list[dict]) -> list[dict]:
        """複数商品を時間分散で出品する

        Args:
            products: 出品する商品のリスト

        Returns:
            出品結果のリスト
        """
        results = []
        for i, product in enumerate(products):
            logger.info("Listing product %d/%d: %s", i + 1, len(products), product.get("name_ja", ""))

            success = False
            if self.navigate_to_exhibit():
                if self.fill_product_form(product):
                    success = self.submit_listing()

            results.append(
                {
                    "product": product.get("name_ja", ""),
                    "success": success,
                }
            )

            # 時間分散：ランダムな間隔を空ける
            if i < len(products) - 1:
                interval = random.randint(
                    LISTING_INTERVAL_MIN * 60,
                    LISTING_INTERVAL_MAX * 60,
                )
                logger.info("Waiting %d seconds before next listing", interval)
                time.sleep(interval)

        return results

    def close(self) -> None:
        """ブラウザを閉じる"""
        self.login_handler.close()
        self.driver = None
