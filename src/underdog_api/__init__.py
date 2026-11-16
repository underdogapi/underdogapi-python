"""Python client for Underdog API (https://underdogapi.com).

Underdog API is an independent REST API for Underdog Fantasy pick'em lines: separate Higher and Lower payout
multipliers, every recorded line move and graded results. It is operated by Stunning Couches LLC and is not
affiliated with Underdog Fantasy.

    from underdog_api import Client
    ud = Client()                      # reads UNDERDOG_API_KEY
    for line in ud.projections(league="NBA", view="compact", limit=5)["data"]:
        print(line)

No dependencies: the standard library only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, Optional

__all__ = ["Client", "UnderdogAPIError", "PlanLimitError", "__version__"]
__version__ = "0.1.1"

DEFAULT_BASE_URL = "https://underdogapi.com"
Transport = Callable[[str, str, Dict[str, str], float], "tuple[int, Dict[str, str], bytes]"]


DEMO_RESOURCES = ("projections", "changes", "coverage", "export", "payouts")

class UnderdogAPIError(Exception):
    """A non-2xx answer. `code`, `message` and the full `body` come from the API's error object."""

    def __init__(self, status: int, body: Any, headers: Optional[Dict[str, str]] = None):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.code = err.get("code")
        self.message = err.get("message") or (body if isinstance(body, str) else "") or f"HTTP {status}"
        super().__init__(f"{status} {self.code or ''} {self.message}".strip())


class PlanLimitError(UnderdogAPIError):
    """402 UPGRADE_REQUIRED: the plan does not include this. No credits were charged.

    `upgrade_url` is a checkout link and `sample` holds a few labelled rows of what was asked for.
    """

    @property
    def upgrade_url(self) -> Optional[str]:
        return (self.body.get("error") or {}).get("upgrade_url") if isinstance(self.body, dict) else None

    @property
    def sample(self) -> list:
        return (self.body.get("error") or {}).get("sample") or [] if isinstance(self.body, dict) else []


def _urllib_transport(method: str, url: str, headers: Dict[str, str], timeout: float):
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict(res.headers.items()), res.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()) if e.headers else {}, e.read()


class Client:
    """One API key, one base URL. Every method returns the parsed JSON body: {"data": [...], "meta": {...}}."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        retries: int = 2,
        transport: Optional[Transport] = None,
        user_agent: str = f"underdog-api-python/{__version__}",
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("UNDERDOG_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._transport = transport or _urllib_transport
        self.user_agent = user_agent

    # -- plumbing ---------------------------------------------------------------------------------------------
    def get(self, path: str, **params: Any) -> Any:
        """GET any documented path, for example client.get("/api/v1/coverage")."""
        query = {k: ("true" if v is True else "false" if v is False else v) for k, v in params.items() if v is not None}
        url = f"{self.base_url}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if self.api_key and not path.startswith("/api/v1/demo/"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempt = 0
        while True:
            status, res_headers, raw = self._transport("GET", url, headers, self.timeout)
            text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            try:
                body: Any = json.loads(text) if text else None
            except ValueError:
                body = text
            if 200 <= status < 300 or status == 304:
                return body
            retry_after = _header(res_headers, "retry-after")
            # Per-minute 429s and 5xx are retried; the monthly 429 (credits used up) is not.
            monthly = isinstance(body, dict) and (body.get("error") or {}).get("code") == "MONTHLY_QUOTA_EXCEEDED"
            if attempt < self.retries and (status >= 500 or (status == 429 and not monthly)):
                attempt += 1
                time.sleep(min(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt, 30))
                continue
            if status == 402:
                raise PlanLimitError(status, body, res_headers)
            raise UnderdogAPIError(status, body, res_headers)

    def pages(self, path: str, **params: Any) -> Iterator[Dict[str, Any]]:
        """Yield rows across pages, following meta.next_cursor with the same filters."""
        cursor = params.pop("cursor", None)
        while True:
            body = self.get(path, cursor=cursor, **params)
            for row in body.get("data") or []:
                yield row
            cursor = (body.get("meta") or {}).get("next_cursor")
            if not cursor:
                return

    # -- endpoints --------------------------------------------------------------------------------------------
    def coverage(self, **p: Any) -> Any:
        """Leagues, stats and the first recorded date per league."""
        return self.get("/api/v1/coverage", **p)

    def projections(self, league: Optional[str] = None, **p: Any) -> Any:
        """The current board. Filters: league, stat, search, payout_tier, status, view=compact, limit, cursor."""
        return self.get("/api/v1/projections", league=league, **p)

    def odds(self, league: Optional[str] = None, **p: Any) -> Any:
        """Each line with its Higher and Lower side as odds entries (5 minutes behind on Free)."""
        return self.get("/api/v1/odds", league=league, **p)

    def history(self, projection_id: str, **p: Any) -> Any:
        """Every recorded change of one market."""
        return self.get(f"/api/v1/projections/{urllib.parse.quote(projection_id)}/history", **p)

    def changes(self, league: Optional[str] = None, **p: Any) -> Any:
        """The change feed: event_type, since, cursor, limit."""
        return self.get("/api/v1/changes", league=league, **p)

    def board(self, as_of: str, league: Optional[str] = None, **p: Any) -> Any:
        """The board as it stood at as_of (ISO timestamp)."""
        return self.get("/api/v1/board", as_of=as_of, league=league, **p)

    def results(self, league: Optional[str] = None, **p: Any) -> Any:
        """Graded lines: player, stat, date (US Eastern), result. Paid plans; Free raises PlanLimitError."""
        return self.get("/api/v1/results", league=league, **p)

    def hit_rates(self, player: str, **p: Any) -> Any:
        """How often a player went Higher or Lower over graded games: stat, league, last."""
        return self.get("/api/v1/hit-rates", player=player, **p)

    def training_set(self, league: Optional[str] = None, **p: Any) -> Any:
        """One labelled row per graded line, for model training. Paid plans."""
        return self.get("/api/v1/training-set", league=league, **p)

    def multipliers(self, league: Optional[str] = None, **p: Any) -> Any:
        return self.get("/api/v1/multipliers", league=league, **p)

    def payouts(self) -> Any:
        """Standard, Flex and Streaks payout reference."""
        return self.get("/api/v1/payouts")

    def credit_costs(self, path: Optional[str] = None) -> Any:
        """The credit policy, or the quote for one request path. No key needed."""
        return self.get("/api/v1/credit-costs", path=path)

    def demo(self, resource: Any = "projections", **p: Any) -> Any:
        """Fictional rows in the live shape, no key: projections, changes, coverage, export, payouts."""
        # demo({"league": "NBA"}) used to request /api/v1/demo/{'league': ...}; a dict first argument is the params.
        if isinstance(resource, dict):
            params = {**resource, **p}
            return self.demo(params.pop("resource", "projections"), **params)
        if resource not in DEMO_RESOURCES:
            raise ValueError(f"demo resource must be one of {', '.join(DEMO_RESOURCES)}; got {resource!r}")
        return self.get(f"/api/v1/demo/{resource}", **p)


def _header(headers: Dict[str, str], name: str) -> Optional[str]:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return v
    return None
