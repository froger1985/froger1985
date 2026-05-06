from __future__ import annotations

import base64
import json
import os
import urllib.parse
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN_FILE = Path("data/ebay_token.json")
_PROD_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
_PROD_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SBX_AUTH_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"
_SBX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
])


class EbayAuth:
    def __init__(self):
        self.client_id = os.getenv("EBAY_CLIENT_ID", "")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET", "")
        self.runame = os.getenv("EBAY_RUNAME", "")
        self.is_sandbox = "SBX" in self.client_id.upper()
        self._auth_url = _SBX_AUTH_URL if self.is_sandbox else _PROD_AUTH_URL
        self._token_url = _SBX_TOKEN_URL if self.is_sandbox else _PROD_TOKEN_URL
        self._token: dict = {}
        self._load_token()

    def _load_token(self):
        if TOKEN_FILE.exists():
            try:
                self._token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._token = {}

    def _save_token(self):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(self._token, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_auth_url(self) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.runame,
            "response_type": "code",
            "scope": SCOPES,
        }
        return f"{self._auth_url}?{urllib.parse.urlencode(params)}"

    def is_authenticated(self) -> bool:
        if not self._token.get("access_token"):
            return False
        return datetime.now().timestamp() < self._token.get("expires_at", 0) - 60

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.runame)

    async def exchange_code(self, code: str) -> bool:
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.runame,
                },
            )
        if resp.status_code != 200:
            return False
        data = resp.json()
        self._token = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": datetime.now().timestamp() + data["expires_in"],
        }
        self._save_token()
        return True

    async def _refresh(self) -> bool:
        if not self._token.get("refresh_token"):
            return False
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._token["refresh_token"],
                    "scope": SCOPES,
                },
            )
        if resp.status_code != 200:
            return False
        data = resp.json()
        self._token["access_token"] = data["access_token"]
        self._token["expires_at"] = datetime.now().timestamp() + data["expires_in"]
        self._save_token()
        return True

    async def get_token(self) -> str | None:
        if self.is_authenticated():
            return self._token["access_token"]
        if await self._refresh():
            return self._token["access_token"]
        return None
