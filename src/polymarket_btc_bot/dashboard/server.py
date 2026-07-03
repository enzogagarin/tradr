from __future__ import annotations

import base64
import json
import os
import secrets
import time
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any

from polymarket_btc_bot.audit import AuditLog, default_audit_path
from polymarket_btc_bot.config import BotSettings
from polymarket_btc_bot.paper import PaperAnalyst
from polymarket_btc_bot.portfolio import PortfolioLedger, default_ledger_path


# Reuse one analyst per settings object so the wallet opportunity report is
# parsed once (not on every poll) and HTTP clients/caches are shared. This is
# the main cause of dashboard lag: a fresh analyst per request re-read and
# re-parsed the wallet JSON and rebuilt every client on each snapshot.
_ANALYST_CACHE: dict[int, PaperAnalyst] = {}


def _analyst_for(settings: BotSettings) -> PaperAnalyst:
    key = id(settings)
    analyst = _ANALYST_CACHE.get(key)
    if analyst is None:
        analyst = PaperAnalyst(settings)
        _ANALYST_CACHE[key] = analyst
    return analyst


def build_demo_snapshot(settings: BotSettings) -> dict[str, Any]:
    return _analyst_for(settings).snapshot()


def _first_line_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return json.loads(line)
    except (OSError, ValueError):
        return None
    return None


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _activity_status(path: Path, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    first = _first_line_json(path)
    session_start = _parse_ts((first or {}).get("observed_ts")) if first else None
    last_evt = decisions[-1] if decisions else None
    last_ts = _parse_ts((last_evt or {}).get("observed_ts")) if last_evt else None
    last_summary = (last_evt or {}).get("summary") or {}
    last_decision = (last_evt or {}).get("decision") or {}

    seconds_since_last = (now - last_ts).total_seconds() if last_ts else None
    uptime_seconds = (now - session_start).total_seconds() if session_start else None

    # Rate over the visible tail window.
    rate = None
    if len(decisions) >= 2:
        t0 = _parse_ts(decisions[0].get("observed_ts"))
        t1 = _parse_ts(decisions[-1].get("observed_ts"))
        if t0 and t1 and (t1 - t0).total_seconds() > 0:
            rate = round(len(decisions) / ((t1 - t0).total_seconds() / 60.0), 1)

    if seconds_since_last is None:
        status = "idle"
    elif seconds_since_last <= 20:
        status = "live"
    elif seconds_since_last <= 90:
        status = "slow"
    else:
        status = "stale"

    return {
        "server_now": now.isoformat(),
        "session_start": session_start.isoformat() if session_start else None,
        "last_activity": last_ts.isoformat() if last_ts else None,
        "uptime_seconds": round(uptime_seconds) if uptime_seconds is not None else None,
        "seconds_since_last": round(seconds_since_last, 1) if seconds_since_last is not None else None,
        "decisions_per_min": rate,
        "activity_status": status,
        "last_action": last_summary.get("action"),
        "last_reason": last_decision.get("reason"),
        "last_execution_status": last_summary.get("execution_status"),
    }


# Cache the recent 5m candles used to resolve paper trades against the real
# close-vs-open outcome, so each dashboard poll does not hammer Binance.
_KLINE_CACHE: tuple[float, dict[int, tuple[float, float, float]]] | None = None
_KLINE_TTL_SECONDS = 5.0


def _recent_5m_klines() -> dict[int, tuple[float, float, float]]:
    """Map cycle-open-epoch -> (open, close, close_epoch) for recent 5m candles."""
    global _KLINE_CACHE
    if _KLINE_CACHE is not None and (time.monotonic() - _KLINE_CACHE[0]) < _KLINE_TTL_SECONDS:
        return _KLINE_CACHE[1]
    try:
        from polymarket_btc_bot.adapters.reference_feeds import BinanceHistoricalKlineClient

        klines = BinanceHistoricalKlineClient().get_klines(symbol="BTCUSDT", interval="5m", limit=64)
        mapping = {
            int(k.open_time.timestamp()): (float(k.open), float(k.close), k.close_time.timestamp())
            for k in klines
        }
        _KLINE_CACHE = (time.monotonic(), mapping)
        return mapping
    except Exception:
        return _KLINE_CACHE[1] if _KLINE_CACHE else {}


def _resolve_event(
    event: dict[str, Any], candle_map: dict[int, tuple[float, float, float]], now_epoch: float
) -> dict[str, Any] | None:
    """Resolve one filled paper trade against the real 5m candle close-vs-open.

    Returns None for non-trades. For filled trades returns resolution with
    keys: resolved (bool), won (bool|None), pnl (float|None). A trade is only
    resolved once its 5m cycle candle has closed; before that it is pending.
    """
    summary = event.get("summary") or {}
    execution = event.get("execution") or {}
    action = summary.get("action", "")
    status = execution.get("status")
    if status not in {"FILLED", "PARTIAL_FILL"} or not action.startswith("BUY"):
        return None
    fill = execution.get("fill") or {}
    shares = float(fill.get("shares") or 0)
    fill_price = float(fill.get("price") or summary.get("target_price") or 0)
    notional = float(fill.get("notional") or 0)
    if shares <= 0:
        return {"resolved": False, "won": None, "pnl": None}

    market = event.get("market") or {}
    start = _parse_ts(market.get("start_ts"))
    if start is None:
        return {"resolved": False, "won": None, "pnl": None}
    cycle_key = int(start.timestamp() // 300) * 300
    candle = candle_map.get(cycle_key)
    if candle is None:
        return {"resolved": False, "won": None, "pnl": None}
    open_price, close_price, close_epoch = candle
    if close_epoch > now_epoch:
        return {"resolved": False, "won": None, "pnl": None}
    up_wins = close_price > open_price
    won = up_wins if action == "BUY_UP" else (not up_wins)
    pnl = shares * (1.0 - fill_price) if won else -notional
    return {"resolved": True, "won": won, "pnl": round(pnl, 2)}


def build_performance_report(
    audit_path: Path | None = None,
    limit: int = 200,
    candle_map: dict[int, tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    path = audit_path or default_audit_path()
    log = AuditLog(path)
    events = log.tail(limit)
    decisions = [e for e in events if e.get("event_type") == "paper_decision"]
    trades = [e for e in decisions if (e.get("summary") or {}).get("action", "").startswith("BUY")]
    fills = [
        e
        for e in decisions
        if (e.get("execution") or {}).get("status") in {"FILLED", "PARTIAL_FILL"}
    ]
    skips = [e for e in decisions if (e.get("summary") or {}).get("action") == "NO_TRADE"]
    buy_up = [e for e in trades if (e.get("summary") or {}).get("action") == "BUY_UP"]
    buy_down = [e for e in trades if (e.get("summary") or {}).get("action") == "BUY_DOWN"]
    total_notional = sum(
        float(((e.get("execution") or {}).get("fill") or {}).get("notional") or 0) for e in fills
    )
    wallet_enhanced = [
        e for e in decisions
        if "wallet_opportunity" in str((e.get("decision") or {}).get("reason", ""))
    ]
    wallet_blocked = [
        e for e in decisions
        if "wallet_avoid" in str((e.get("decision") or {}).get("reason", ""))
    ]

    # Real resolution + equity curve.
    # Each filled trade is resolved against the ACTUAL Binance 5m candle for its
    # cycle: UP wins if candle close > open, DOWN wins if close < open. Winner
    # payout = shares * (1 - fill_price); loser loses the paid notional. Trades
    # whose candle has not closed yet are pending (not counted in P&L). This is
    # a genuine ~50/50 outcome, replacing the earlier tautological rig.
    if candle_map is None:
        candle_map = _recent_5m_klines()
    now_epoch = datetime.now(tz=UTC).timestamp()
    resolutions: dict[int, dict[str, Any]] = {}
    equity_curve: list[dict[str, Any]] = []
    running = 0.0
    wins = 0
    losses = 0
    pending = 0
    for e in decisions:
        res = _resolve_event(e, candle_map, now_epoch)
        if res is None:
            continue
        resolutions[id(e)] = res
        if not res["resolved"]:
            pending += 1
            continue
        running += res["pnl"]
        if res["won"]:
            wins += 1
        else:
            losses += 1
        equity_curve.append(
            {
                "ts": (e.get("summary") or {}).get("observed_ts") or e.get("observed_ts"),
                "pnl": res["pnl"],
                "equity": round(running, 2),
                "won": res["won"],
                "action": (e.get("summary") or {}).get("action"),
            }
        )
    resolved = wins + losses
    report = {
        "total_decisions": len(decisions),
        "total_trades": len(trades),
        "total_fills": len(fills),
        "total_skips": len(skips),
        "buy_up_count": len(buy_up),
        "buy_down_count": len(buy_down),
        "total_fill_notional": round(total_notional, 2),
        "wallet_enhanced_count": len(wallet_enhanced),
        "wallet_blocked_count": len(wallet_blocked),
        "trade_rate": round(len(trades) / max(1, len(decisions)), 4),
        "fill_rate": round(len(fills) / max(1, len(trades)), 4),
        "estimated_pnl": round(running, 2),
        "resolved_trades": resolved,
        "pending_trades": pending,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / max(1, resolved), 4),
        "equity_curve": equity_curve[-120:],
        **_activity_status(path, decisions),
        "recent_decisions": [
            {
                "ts": e.get("observed_ts"),
                "action": (e.get("summary") or {}).get("action"),
                "edge": (e.get("summary") or {}).get("edge"),
                "btc_price": (e.get("summary") or {}).get("btc_price"),
                "reference_price": (e.get("summary") or {}).get("reference_price"),
                "execution_status": (e.get("summary") or {}).get("execution_status"),
                "reason": (e.get("decision") or {}).get("reason"),
                "fill_notional": ((e.get("execution") or {}).get("fill") or {}).get("notional"),
                "fill_shares": ((e.get("execution") or {}).get("fill") or {}).get("shares"),
                "pnl": (resolutions.get(id(e)) or {}).get("pnl"),
                "resolved": (resolutions.get(id(e)) or {}).get("resolved", False),
                "won": (resolutions.get(id(e)) or {}).get("won"),
            }
            for e in reversed(decisions[-30:])
        ],
    }
    if audit_path is None:
        report = _merge_ledger_performance(report, default_ledger_path())
    return report


def _merge_ledger_performance(report: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    """Prefer the persistent paper portfolio for PnL/exposure KPIs.

    The audit log still powers activity/recent-decision UX, but the ledger is
    the source of truth for money because it records fees, fills, open
    positions, and real settlements.
    """
    if not ledger_path.exists():
        return report
    ledger = PortfolioLedger.load(ledger_path)
    if not ledger.positions:
        return report

    settled = [p for p in ledger.positions if p.status == "SETTLED"]
    open_positions = [p for p in ledger.positions if p.status == "OPEN"]
    wins = sum(1 for p in settled if p.won)
    losses = sum(1 for p in settled if p.won is False)
    running = 0.0
    equity_curve: list[dict[str, Any]] = []
    for pos in sorted(settled, key=lambda p: p.settled_ts or p.opened_ts):
        running += pos.realized_pnl
        equity_curve.append(
            {
                "ts": pos.settled_ts or pos.opened_ts,
                "pnl": round(pos.realized_pnl, 2),
                "equity": round(running, 2),
                "won": pos.won,
                "action": f"BUY_{pos.outcome}",
            }
        )

    summary = ledger.summary()
    report.update(
        {
            "total_trades": len(ledger.positions),
            "total_fills": len(ledger.positions),
            "total_fill_notional": round(sum(p.cost for p in ledger.positions), 2),
            "estimated_pnl": round(summary["realized_pnl"], 2),
            "resolved_trades": len(settled),
            "pending_trades": len(open_positions),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / max(1, wins + losses), 4),
            "equity_curve": equity_curve[-120:],
            "portfolio": summary,
        }
    )
    return report


class DashboardHandler(SimpleHTTPRequestHandler):
    settings: BotSettings
    static_dir: Path

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def _parse_path(self) -> tuple[str, dict[str, str]]:
        """Split path and query params."""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return parsed.path, params

    # Non-sensitive static assets are served without auth so the styled page and
    # its scripts always load; the token only gates the index page and the data
    # APIs. app.js then attaches the token (from localStorage) to /api calls.
    _PUBLIC_SUFFIXES = (".css", ".js", ".woff", ".woff2", ".ttf", ".ico", ".png", ".svg", ".map")

    def do_GET(self) -> None:
        path, params = self._parse_path()
        needs_auth = path in {"/", "/index.html"} or path.startswith("/api/")
        is_public_asset = path.endswith(self._PUBLIC_SUFFIXES)
        if needs_auth and not is_public_asset:
            if not self._check_auth():
                return
        self.path = path
        if self.path == "/api/snapshot":
            body = json.dumps(build_demo_snapshot(self.settings), indent=2).encode("utf-8")
            self._send_json(body)
            return
        if self.path == "/api/performance":
            body = json.dumps(build_performance_report(), indent=2).encode("utf-8")
            self._send_json(body)
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _send_json(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        user = self.settings.dashboard_auth_user
        pw = self.settings.dashboard_auth_password
        if not pw:
            return True
        # 1) HTTP Basic Auth header
        header = self.headers.get("Authorization", "")
        expected = base64.b64encode(f"{user or ''}:{pw}".encode()).decode()
        if header == f"Basic {expected}":
            return True
        # 2) Query-string token (?token=...) for browsers that can't do Basic Auth
        _, params = self._parse_path()
        token = params.get("token")
        if token and token == pw:
            return True
        # 3) Cookie-based session
        cookie = self.headers.get("Cookie", "")
        if f"paz_token={pw}" in cookie:
            return True
        # Return a login page for browsers
        is_browser = "text/html" in self.headers.get("Accept", "")
        if is_browser:
            login_html = (
                "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<title>BTC Paper Desk \u00b7 Login</title>"
                "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap' rel='stylesheet'>"
                "<style>"
                "*{box-sizing:border-box}"
                "body{font-family:Inter,system-ui,sans-serif;margin:0;height:100vh;color:#f2f5fa;"
                "display:flex;align-items:center;justify-content:center;"
                "background:radial-gradient(900px 500px at 70% -10%,rgba(91,140,255,.12),transparent 60%),#0a0c10}"
                ".box{background:#12151c;border:1px solid #232936;padding:2.4rem 2rem;border-radius:16px;"
                "max-width:360px;width:90%;box-shadow:0 24px 60px rgba(0,0,0,.5)}"
                ".mark{width:52px;height:52px;border-radius:14px;display:grid;place-items:center;"
                "background:linear-gradient(145deg,#f7931a,#b5670f);font-size:28px;font-weight:800;"
                "margin:0 auto 1rem;box-shadow:0 8px 22px rgba(247,147,26,.3)}"
                "h2{margin:0 0 .3rem;font-size:1.25rem;text-align:center}"
                "p{margin:0 0 1.4rem;text-align:center;color:#8b95a7;font-size:.85rem}"
                "input{width:100%;padding:.8rem 1rem;border:1px solid #313a4c;border-radius:10px;"
                "background:#0e1116;color:#f2f5fa;font-size:1rem;outline:none;transition:border .15s}"
                "input:focus{border-color:#5b8cff}"
                "button{width:100%;padding:.85rem;margin-top:1rem;border:none;border-radius:10px;"
                "background:linear-gradient(120deg,#5b8cff,#9b7bff);color:#fff;font-weight:700;"
                "font-size:1rem;cursor:pointer;transition:transform .12s}"
                "button:hover{transform:translateY(-1px)}"
                "</style></head><body>"
                "<div class='box'><div class='mark'>\u20bf</div>"
                "<h2>BTC Paper Desk</h2><p>Enter access password</p>"
                "<form onsubmit='return doLogin()'>"
                "<input id='pw' type='password' placeholder='Password' autofocus>"
                "<button type='submit'>Enter dashboard</button></form></div>"
                "<script>function doLogin(){var pw=document.getElementById('pw').value;"
                "window.location.href='/?token='+encodeURIComponent(pw);return false;}</script>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(login_html)))
            self.end_headers()
            self.wfile.write(login_html)
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Polymarket Bot Dashboard"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.wfile.write(b"Unauthorized")
        return False

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_dashboard(settings: BotSettings) -> None:
    static_dir = Path(str(files("polymarket_btc_bot.dashboard")))
    handler = type(
        "ConfiguredDashboardHandler",
        (DashboardHandler,),
        {"settings": settings, "static_dir": static_dir},
    )
    host = settings.dashboard_host
    port = settings.dashboard_port
    server = ThreadingHTTPServer((host, port), handler)
    url_host = host if host != "0.0.0.0" else "<server-ip>"
    auth_hint = " (auth: on)" if settings.dashboard_auth_password else ""
    print(f"Dashboard running at http://{url_host}:{port}{auth_hint}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
