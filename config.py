"""プロジェクト設定・定数"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# プロジェクトルート
BASE_DIR = Path(__file__).resolve().parent

# BUYMA認証情報
BUYMA_EMAIL = os.getenv("BUYMA_EMAIL", "")
BUYMA_PASSWORD = os.getenv("BUYMA_PASSWORD", "")

# BUYMA URL
BUYMA_LOGIN_URL = "https://www.buyma.com/login/"
BUYMA_EXHIBIT_URL = "https://www.buyma.com/contents/exhibit/"

# baseblu設定
BASEBLU_BASE_URL = "https://www.baseblu.com"
BASEBLU_SALE_URL = f"{BASEBLU_BASE_URL}/en/sale"

# Selenium設定
SELENIUM_HEADLESS = os.getenv("SELENIUM_HEADLESS", "true").lower() == "true"
SELENIUM_TIMEOUT = int(os.getenv("SELENIUM_TIMEOUT", "30"))

# 出品設定
MIN_PROFIT_RATE = float(os.getenv("MIN_PROFIT_RATE", "0.20"))  # 最低利益率20%
LISTING_INTERVAL_MIN = int(os.getenv("LISTING_INTERVAL_MIN", "5"))  # 出品間隔（分）
LISTING_INTERVAL_MAX = int(os.getenv("LISTING_INTERVAL_MAX", "15"))

# ファイルパス
DATA_DIR = BASE_DIR / "templates"
LOG_DIR = BASE_DIR / "logs"
CSV_OUTPUT_DIR = BASE_DIR / "output"

# 為替レート（EUR→JPY）環境変数で上書き可能
EUR_TO_JPY = float(os.getenv("EUR_TO_JPY", "160.0"))

# BUYMA手数料率
BUYMA_COMMISSION_RATE = 0.058  # 5.8%

# 国際送料（目安、EUR）
SHIPPING_COST_EUR = float(os.getenv("SHIPPING_COST_EUR", "30.0"))
