from __future__ import annotations

import csv
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import requests

from py_sec_edgar.config import load_config
from py_sec_edgar.rate_limit import get_shared_rate_limiter

logger = logging.getLogger(__name__)


class ProxyRequest(object):
    """Legacy downloader interface with safer HTTP behavior.

    Notes:
    - Keeps legacy class/method names for compatibility.
    - Uses a persistent requests.Session.
    - Uses one declared SEC-compliant User-Agent by default.
    - Proxy mode is explicit opt-in compatibility behavior.
    """

    def __init__(self, CONFIG=None, session: requests.Session | None = None, rate_limiter=None):
        self.retry_counter = 3
        self.backoff_seconds = 1.0
        self.pause_for_courtesy = False
        self.last_failure: dict[str, Any] | None = None

        app_config = load_config()
        self.user_agent = getattr(CONFIG, "user_agent", app_config.user_agent)
        self.connect_timeout = float(getattr(CONFIG, "request_timeout_connect", app_config.request_timeout_connect))
        self.read_timeout = float(getattr(CONFIG, "request_timeout_read", app_config.request_timeout_read))
        self.max_requests_per_second = float(
            getattr(CONFIG, "max_requests_per_second", app_config.max_requests_per_second)
        )

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.rate_limiter = rate_limiter or get_shared_rate_limiter(self.max_requests_per_second)

        self.use_proxy = False
        self.random_proxy_host = None
        self.random_header = {"User-Agent": self.user_agent}

        if CONFIG:
            self.USERNAME = os.getenv("PP_USERNAME")
            self.PASSWORD = os.getenv("PP_PASSWORD")
            self.VPN_LIST = os.getenv("PP_SERVER_LIST")
            self.port = 5080
            self.service = "socks5"

            if self.USERNAME and self.PASSWORD and self.VPN_LIST and os.path.exists(self.VPN_LIST):
                self.proxies = self._load_proxy_ips(self.VPN_LIST)
                self.use_proxy = len(self.proxies) > 0
            else:
                self.proxies = []
        else:
            self.proxies = []

    def _load_proxy_ips(self, proxy_csv: str) -> list[str]:
        with open(proxy_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row["IP"].strip() for row in reader if row.get("IP") and row["IP"].strip()]

    def generate_random_proxy_hosts(self):
        if not self.proxies:
            return None

        proxy = random.choice(self.proxies)
        proxies = {
            "http": f"{self.service}://{self.USERNAME}:{self.PASSWORD}@{proxy}:{self.port}",
            "https": f"{self.service}://{self.USERNAME}:{self.PASSWORD}@{proxy}:{self.port}",
        }
        logger.info("Proxy selected for compatibility mode", extra={"proxy_host": proxy})
        return proxies

    def generate_random_header(self):
        # Random browser UAs are intentionally removed from default behavior.
        return {"User-Agent": self.user_agent}

    def generate_random_header_and_proxy_host(self):
        self.random_proxy_host = self.generate_random_proxy_hosts() if self.use_proxy else None
        self.random_header = self.generate_random_header()
        if self.pause_for_courtesy:
            time.sleep(random.randrange(1, 3))

    def _status_reason(self, status_code: int) -> str:
        if status_code == 403:
            return "forbidden"
        if status_code == 404:
            return "not_found"
        if status_code == 429:
            return "rate_limited"
        if 500 <= status_code <= 599:
            return "server_error"
        return "http_error"

    def _is_transient(self, status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code <= 599

    def _record_failure(self, *, url: str, filepath: str, attempt: int, reason: str, status_code: int | None, error: str | None):
        self.last_failure = {
            "url": url,
            "filepath": filepath,
            "attempt": attempt,
            "reason": reason,
            "status_code": status_code,
            "error": error,
        }
        logger.warning("Download failed", extra={"download_failure": self.last_failure})

    def _perform_get(self, url: str, *, stream: bool):
        self.rate_limiter.wait()
        self.generate_random_header_and_proxy_host()
        response = self.session.get(
            url,
            stream=stream,
            headers=self.random_header,
            proxies=self.random_proxy_host,
            timeout=(self.connect_timeout, self.read_timeout),
        )
        self.r = response
        return response

    def GET_RESPONSE(self, url, stream=False):
        for attempt in range(1, self.retry_counter + 1):
            try:
                response = self._perform_get(url, stream=stream)
                status_code = response.status_code
                if status_code >= 400:
                    reason = self._status_reason(status_code)
                    self._record_failure(
                        url=url,
                        filepath="",
                        attempt=attempt,
                        reason=reason,
                        status_code=status_code,
                        error=None,
                    )
                    if self._is_transient(status_code) and attempt < self.retry_counter:
                        time.sleep(self.backoff_seconds * attempt)
                        continue
                    return None
                return response
            except requests.RequestException as exc:
                self._record_failure(
                    url=url,
                    filepath="",
                    attempt=attempt,
                    reason="request_exception",
                    status_code=None,
                    error=str(exc),
                )
                if attempt < self.retry_counter:
                    time.sleep(self.backoff_seconds * attempt)
                    continue
                return None
        return None

    def GET_FILE(self, url, filepath):
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, self.retry_counter + 1):
            tmp_path = target.with_suffix(target.suffix + ".tmp")
            try:
                response = self._perform_get(url, stream=True)

                status_code = response.status_code
                if status_code >= 400:
                    reason = self._status_reason(status_code)
                    self._record_failure(
                        url=url,
                        filepath=str(target),
                        attempt=attempt,
                        reason=reason,
                        status_code=status_code,
                        error=None,
                    )
                    if self._is_transient(status_code) and attempt < self.retry_counter:
                        time.sleep(self.backoff_seconds * attempt)
                        continue
                    return False

                content_type = response.headers.get("Content-Type", "")
                if "text/html" in content_type.lower() and target.suffix.lower() in {".txt", ".idx", ".xml"}:
                    self._record_failure(
                        url=url,
                        filepath=str(target),
                        attempt=attempt,
                        reason="unexpected_content_type",
                        status_code=status_code,
                        error=f"content_type={content_type}",
                    )
                    return False

                with open(tmp_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            handle.write(chunk)

                os.replace(tmp_path, target)
                logger.info("Download success", extra={"url": url, "filepath": str(target), "status_code": status_code})
                return True

            except requests.RequestException as exc:
                self._record_failure(
                    url=url,
                    filepath=str(target),
                    attempt=attempt,
                    reason="request_exception",
                    status_code=None,
                    error=str(exc),
                )
                if attempt < self.retry_counter:
                    time.sleep(self.backoff_seconds * attempt)
                    continue
                return False
            finally:
                if tmp_path.exists() and not target.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

        return False


if __name__ == "__main__":
    from py_sec_edgar.settings import CONFIG

    url = r"https://www.sec.gov/Archives/edgar/data/897078/0001493152-18-009029.txt"
    g = ProxyRequest()
    local_master_idx = os.path.join(CONFIG.FULL_INDEX_DIR, "master.idx")
    g.GET_FILE(url, local_master_idx)
