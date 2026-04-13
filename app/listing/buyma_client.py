"""BUYMA 操作の共通ラッパー（フィールド入力・ログイン・画像アップロード等）"""

import logging
from typing import List, Optional

from app.core.config import get_config

logger = logging.getLogger(__name__)


class BUYMAClient:
    """
    Playwright Page を通じて BUYMA 上の各種操作を行うラッパー。
    ログイン、フィールド入力、画像アップロード、出品実行等を担当する。
    """

    # 出品フォームの CSS セレクタマッピング
    _FIELD_SELECTORS: dict[str, str] = {
        "brand": "#brand_input",
        "title": "#product_name",
        "category": "#category_select",
        "sku": "#sku_input",
        "description": "#product_description",
        "price": "#price_input",
    }

    def __init__(self, page) -> None:
        self.page = page
        self.config = get_config()

    # ------------------------------------------------------------------
    # ログイン
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """
        BUYMA にログインする。

        Returns:
            成功時 True、失敗時 False
        """
        try:
            self.page.goto("https://www.buyma.com/login/", timeout=30000)
            self.page.wait_for_load_state("networkidle")
            self.page.fill("#email", self.config.buyma_email)
            self.page.fill("#password", self.config.buyma_password)
            self.page.click("button[type=submit]")
            self.page.wait_for_load_state("networkidle")
            logger.info("Logged in to BUYMA as %s", self.config.buyma_email)
            return True
        except Exception as exc:
            logger.error("BUYMA login failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # ナビゲーション
    # ------------------------------------------------------------------

    def navigate_to_listing_form(self) -> None:
        """BUYMA 出品フォームへ移動する。"""
        self.page.goto("https://www.buyma.com/contents/exhibit/", timeout=30000)
        self.page.wait_for_load_state("networkidle")

    # ------------------------------------------------------------------
    # フィールド入力
    # ------------------------------------------------------------------

    def set_field(self, field_name: str, value: str) -> None:
        """
        出品フォームの指定フィールドに値を入力する。

        Args:
            field_name: フィールド名（_FIELD_SELECTORS のキー）
            value: 入力値

        Raises:
            ValueError: 未知のフィールド名
        """
        selector = self._FIELD_SELECTORS.get(field_name)
        if not selector:
            raise ValueError(f"Unknown field: {field_name}")
        self.page.fill(selector, value)
        logger.debug("Set %s = %s", field_name, value[:50] if value else "")

    # ------------------------------------------------------------------
    # 画像アップロード
    # ------------------------------------------------------------------

    def upload_images(self, image_urls: List[str]) -> None:
        """
        複数の画像をアップロードする（メイン 1 + サブ最大 5 = 最大 6 枚）。

        注意: ページ遷移直後に実行すること（遅延すると 403 エラーが発生する）。

        Args:
            image_urls: アップロードする画像 URL リスト
        """
        from app.utils.images import download_image

        for idx, url in enumerate(image_urls[:6]):
            try:
                local_path = download_image(url)
                upload_btn_selector = f"[data-image-upload-{idx}]"
                self.page.click(upload_btn_selector)
                self.page.set_input_files("input[type=file]", local_path)
                self.page.wait_for_load_state("networkidle")
                logger.debug("Uploaded image %d: %s", idx + 1, url)
            except Exception as exc:
                logger.warning("Failed to upload image %d (%s): %s", idx + 1, url, exc)

    # ------------------------------------------------------------------
    # 出品オプション設定
    # ------------------------------------------------------------------

    def set_listing_options(
        self,
        buyable: bool = True,
        purchase_limit_days: int = 90,
        tax_included: bool = True,
        buy_location: str = "Italy",
        ship_from: str = "Japan",
    ) -> None:
        """
        出品オプションを設定する。

        Args:
            buyable: 買付可否（True = 買付可）
            purchase_limit_days: 購入期限（日数）
            tax_included: 関税出品者負担の場合 True
            buy_location: 買付地
            ship_from: 発送地
        """
        try:
            self.page.select_option("#purchaseable", "yes" if buyable else "no")
            self.page.fill("#purchase_limit_days", str(purchase_limit_days))
            if tax_included:
                self.page.check("#tax_included")
            else:
                self.page.uncheck("#tax_included")
            self.page.select_option("#buy_location", buy_location)
            self.page.select_option("#ship_from", ship_from)
        except Exception as exc:
            logger.warning("Failed to set some listing options: %s", exc)

    # ------------------------------------------------------------------
    # 保存・出品
    # ------------------------------------------------------------------

    def save_as_draft(self) -> None:
        """下書きとして保存する。"""
        self.page.click("button[data-action=save-draft]")
        self.page.wait_for_load_state("networkidle")
        logger.info("Saved as draft")

    def publish(self) -> str:
        """
        出品を公開する。

        Returns:
            BUYMA item_id（URL の末尾から抽出）
        """
        self.page.click("button[data-action=publish]")
        self.page.wait_for_load_state("networkidle")

        # item_id を URL から抽出
        item_id = self.page.url.rstrip("/").split("/")[-1] or "unknown"
        logger.info("Published: item_id=%s", item_id)
        return item_id
