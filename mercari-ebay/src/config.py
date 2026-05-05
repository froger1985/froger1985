from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BASE_DIR / "config.yaml"


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


CONFIG = load_config()

# Mercari
MERCARI_SESSION_TOKEN = os.getenv("MERCARI_SESSION_TOKEN", "")

# eBay Trading API credentials
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_DEV_ID = os.getenv("EBAY_DEV_ID", "")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID", "")
EBAY_USER_TOKEN = os.getenv("EBAY_USER_TOKEN", "")
EBAY_SELLER_EMAIL = os.getenv("EBAY_SELLER_EMAIL", "")

# Notifications
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")

# Exchange rate (manual override)
USD_JPY_RATE_OVERRIDE = os.getenv("USD_JPY_RATE", "")

# DB path
DB_PATH = _BASE_DIR / CONFIG["database"]["path"]
