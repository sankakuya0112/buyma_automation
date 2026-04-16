"""BUYMA 操作の共通ラッパー（フィールド入力・ログイン・画像アップロード等）"""

import logging
import time
from typing import List, Optional

from app.core.config import get_config

logger = logging.getLogger(__name__)

# BUYMA 出品フォーム URL
_LISTING_FORM_URL = "https://www.buyma.com/contents/exhibit/"
_LOGIN_URL = "https://www.buyma.com/login/"


class BUYMAClient:
    """
    Playwright Page を通じて BUYMA 上の各種操作を行うラッパー。
    セレクタは cowork (Claude.ai) による実際のフォーム解析結果に基づく。
    """

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
            self.page.goto(_LOGIN_URL, timeout=30000)
            self.page.wait_for_load_state("networkidle")
            # 実際のセレクタ（cowork 解析済み）
            self.page.fill('input[name="txtLoginId"]', self.config.buyma_email)
            self.page.fill('input[name="txtLoginPass"]', self.config.buyma_password)
            self.page.click('input[id="login_do"]')
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
        self.page.goto(_LISTING_FORM_URL, timeout=30000)
        self.page.wait_for_load_state("networkidle")
        time.sleep(1)  # React コンポーネントの描画待ち

    # ------------------------------------------------------------------
    # タイトル
    # ------------------------------------------------------------------

    def set_title(self, value: str) -> None:
        """商品タイトルを入力する（最初の text input）。"""
        inputs = self.page.locator('input[type="text"]')
        inputs.nth(0).fill(value)
        logger.debug("Set title: %s", value[:50])

    # ------------------------------------------------------------------
    # 商品説明
    # ------------------------------------------------------------------

    def set_description(self, value: str) -> None:
        """商品説明を入力する（最初の textarea）。"""
        self.page.locator("textarea").nth(0).fill(value)
        logger.debug("Set description (%d chars)", len(value))

    # ------------------------------------------------------------------
    # 価格
    # ------------------------------------------------------------------

    def set_price(self, price_jpy: int) -> None:
        """
        商品価格を入力する。
        ラベルテキスト「商品価格」から入力欄を特定する。
        """
        js = """
        (price) => {
            const labels = document.querySelectorAll(
                'label, th, dt, .bmm-c-summary__ttl, .bmm-c-form__label'
            );
            for (const label of labels) {
                if (!label.textContent.includes('商品価格')) continue;
                let el = label.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!el) break;
                    const input = el.querySelector('input[type="text"], input[type="number"]');
                    if (input) {
                        const setter = Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(input, String(price));
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        return true;
                    }
                    el = el.parentElement;
                }
            }
            return false;
        }
        """
        result = self.page.evaluate(js, price_jpy)
        if not result:
            logger.warning("価格フィールドが見つかりませんでした")
        else:
            logger.debug("Set price: ¥%d", price_jpy)

    # ------------------------------------------------------------------
    # ブランド
    # ------------------------------------------------------------------

    def set_brand(self, brand_ja: str) -> None:
        """
        ブランドを入力する（8 番目の input → サジェスト選択）。
        """
        inputs = self.page.locator("input")
        inputs.nth(7).fill(brand_ja)
        time.sleep(0.8)

        suggestion = self.page.locator(".bmm-c-suggest__option--selectable").first
        if suggestion.count() > 0:
            suggestion.click()
            logger.debug("Set brand via suggestion: %s", brand_ja)
        else:
            logger.warning("ブランドサジェストが表示されませんでした: %s", brand_ja)

    # ------------------------------------------------------------------
    # 色（タブ切替 → React Select）
    # ------------------------------------------------------------------

    def set_color(self, color: str) -> None:
        """
        色タブを開き React Select で色を選択する。
        """
        try:
            # 「色」タブをクリック
            color_tab = self.page.locator('[role="tab"]', has_text="色").first
            color_tab.click()
            time.sleep(0.5)

            # パネル内の React Select を操作
            panel = self.page.locator("#react-tabs-1")
            select = panel.locator(".Select").first
            select.locator(".Select-control, [class*='-control']").click()
            time.sleep(0.4)

            search_input = select.locator(
                '.Select-input input, input[role="combobox"]'
            ).first
            search_input.fill(color)
            time.sleep(0.6)

            option = self.page.locator(
                ".Select-option, [class*='-option']:not([class*='disabled'])"
            ).first
            if option.count() > 0:
                option.click()
                logger.debug("Set color: %s", color)
            else:
                logger.warning("色の候補が表示されませんでした: %s", color)
        except Exception as exc:
            logger.warning("色の設定に失敗: %s", exc)

    # ------------------------------------------------------------------
    # 画像アップロード（BUYMA 画像 API 経由）
    # ------------------------------------------------------------------

    def upload_images(self, image_urls: List[str]) -> int:
        """
        画像を BUYMA の API 経由でアップロードする。

        Returns:
            アップロード成功件数
        """
        import requests

        # CSRF トークンを取得
        csrf_token = self.page.locator('meta[name="csrf-token"]').get_attribute("content") or ""
        cookies = {c["name"]: c["value"] for c in self.page.context.cookies()}

        count = 0
        for idx, url in enumerate(image_urls[:5]):
            try:
                img_resp = requests.get(url, timeout=15)
                img_resp.raise_for_status()

                ext = img_resp.headers.get("Content-Type", "image/jpeg").split("/")[-1]
                files = {"item_image[image]": (f"image_{idx + 1}.{ext}", img_resp.content)}
                headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}

                upload_resp = requests.post(
                    "https://www.buyma.com/rorapi/item_image.json",
                    files=files,
                    headers=headers,
                    cookies=cookies,
                    timeout=30,
                )
                upload_resp.raise_for_status()
                count += 1
                logger.debug("Uploaded image %d: %s", idx + 1, url)
                time.sleep(0.5)
            except Exception as exc:
                logger.warning("画像アップロード失敗 %d (%s): %s", idx + 1, url, exc)

        return count

    # ------------------------------------------------------------------
    # 保存・出品ボタン
    # ------------------------------------------------------------------

    def save_as_draft(self) -> None:
        """下書きとして保存する。"""
        self.page.locator("button", has_text="下書き保存する").click()
        self.page.wait_for_load_state("networkidle")
        logger.info("Saved as draft")

    def publish(self) -> str:
        """
        出品を公開する。

        Returns:
            BUYMA item_id（URL から抽出）
        """
        # 確認画面へ
        self.page.locator("button", has_text="入力内容を確認する").click()
        self.page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 公開する
        self.page.locator("button", has_text="公開する").click()
        self.page.wait_for_load_state("networkidle")

        item_id = self.page.url.rstrip("/").split("/")[-1] or "unknown"
        logger.info("Published: item_id=%s", item_id)
        return item_id
