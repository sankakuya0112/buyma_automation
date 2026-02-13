"""BUYMAログイン処理"""

import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    BUYMA_EMAIL,
    BUYMA_LOGIN_URL,
    BUYMA_PASSWORD,
    SELENIUM_HEADLESS,
    SELENIUM_TIMEOUT,
)

logger = logging.getLogger(__name__)


class BuymaLogin:
    """BUYMAへのログイン・ブラウザセッション管理"""

    def __init__(self):
        self.driver: webdriver.Chrome | None = None

    def setup_driver(self) -> webdriver.Chrome:
        """Chromeドライバーを設定・起動する"""
        options = Options()
        if SELENIUM_HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        self.driver = webdriver.Chrome(service=Service(), options=options)
        self.driver.implicitly_wait(SELENIUM_TIMEOUT)
        logger.info("Chrome driver initialized")
        return self.driver

    def login(self, email: str | None = None, password: str | None = None) -> bool:
        """BUYMAにログインする"""
        if not self.driver:
            self.setup_driver()

        _email = email or BUYMA_EMAIL
        _password = password or BUYMA_PASSWORD

        if not _email or not _password:
            logger.error("BUYMA credentials not configured")
            return False

        try:
            self.driver.get(BUYMA_LOGIN_URL)
            wait = WebDriverWait(self.driver, SELENIUM_TIMEOUT)

            # TODO: 実際のBUYMAログインフォームのセレクタに合わせて調整
            email_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='email'], #txtLoginId"))
            )
            email_input.clear()
            email_input.send_keys(_email)

            password_input = self.driver.find_element(
                By.CSS_SELECTOR, "input[name='password'], #txtLoginPass"
            )
            password_input.clear()
            password_input.send_keys(_password)

            login_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], #btnLogin"
            )
            login_button.click()

            # ログイン成功確認
            wait.until(EC.url_changes(BUYMA_LOGIN_URL))
            logger.info("BUYMA login successful")
            return True

        except Exception:
            logger.exception("BUYMA login failed")
            return False

    def close(self) -> None:
        """ブラウザを閉じる"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("Browser closed")
