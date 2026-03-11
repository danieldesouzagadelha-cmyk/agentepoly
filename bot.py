"""
=================================================================
         POLYMARKET FOOTBALL BOT - Automatic Trading Agent
   Strategy: Pre-game buy + In-game sell on events (goals)
=================================================================
"""

import os
import json
import time
import logging
import schedule
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple
from dotenv import load_dotenv

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, Side
    from py_clob_client.constants import POLYGON
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("[WARNING] py-clob-client not installed. Running in SIMULATION mode.")

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger("PolyBot")


def telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        log.debug("Telegram error: " + str(e))


@dataclass
class BotConfig:
    max_position_usdc: float = 50.0
    max_open_positions: int = 5
    total_bankroll_usdc: float = 500.0
    bankroll_risk_pct: float = 0.05
    min_odds: float = 0.25
    max_odds: float = 0.75
    min_hours_before_game: float = 1.0
    max_hours_before_game: float = 48.0
    sell_on_favorable_goal: bool = True
    sell_on_adverse_goal: bool = True
    profit_target_pct: float = 0.30
    stop_loss_pct: float = 0.40
    sell_after_minutes: int = 70
    host: str = "https://clob.polymarket.com"
    chain_id: int = POLYGON if CLOB_AVAILABLE else 137
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    sportradar_key: str = field(default_factory=lambda: os.getenv("SPORTRADAR_API_KEY", ""))
    simulation_mode: bool = True


CONFIG = BotConfig()


@dataclass
class Match:
    match_id: str
    home_team: str
    away_team: str
    start_time: datetime
    league: str
    polymarket_condition_id: str = ""
    home_win_token_id: str = ""
    draw_token_id: str = ""
    away_win_token_id: str = ""
    home_odds: float = 0.0
    draw_odds: float = 0.0
    away_odds: float = 0.0
    minute: int = 0
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"


@dataclass
class Position:
    position_id: str
    match: Match
    outcome: str
    token_id: str
    entry_price: float
    size_usdc: float
    shares: float
    entry_time: datetime
    status: str = "open"
    exit_price: float = 0.0
    pnl_usdc: float = 0.0
    sell_reason: str = ""


class PolymarketClient:
    def __init__(self, config: BotConfig):
        self.config = config
        self.client = None
        self.simulation_mode = config.simulation_mode
        if not self.simulation_mode and CLOB_AVAILABLE:
            self._init_real_client()
        else:
            log.info("[SIM] SIMULATION MODE - No real orders will be placed")

    def _init_real_client(self):
        try:
            self.client = ClobClient(
                host=self.config.host,
                chain_id=self.config.chain_id,
                key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                signature_type=2,
                funder=os.getenv("POLYMARKET_WALLET_ADDRESS")
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            log.info("[OK] Polymarket client initialized")
        except Exception as e:
            log.error("Failed to init: " + str(e))
            self.simulation_mode = True

    def get_mid_price(self, token_id):
        try:
            url = "https://clob.polymarket.com/book?token_id=" + token_id
            resp = requests.get(url, timeout=5).json()
            best_bid = float(resp["bids"][0]["price"]) if resp.get("bids") else 0
            best_ask = float(resp["asks"][0]["price"]) if resp.get("asks") else 1
            return (best_bid + best_ask) / 2
        except:
            return 0.0

    def place_buy_order(self, token_id, size_usdc, price):
        if self.simulation_mode:
            log.info("[SIM] BUY " + str(size_usdc) + " USDC @ " + str(round(price, 4)))
            return {"success": True, "order_id": "SIM-" + str(int(time.time())), "simulated": True}
        try:
            shares = size_usdc / price
            resp = self.client.create_and_post_order(OrderArgs(price=price, size=shares, side=Side.BUY, token_id=token_id))
            return {"success": True, "order_id": resp.get("orderID", "")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def place_sell_order(self, token_id, shares, price):
        if self.simulation_mode:
            log.info("[SIM] SELL " + str(round(shares, 4)) + " @ " + str(round(price, 4)))
            return {"success": True, "order_id": "SIM-SELL-" + str(int(time.time())), "simulated": True}
        try:
            resp = self.client.create_and_post_order(OrderArgs(price=price, size=shares, side=Side.SELL, token_id=token_id))
            return {"success": True, "order_id": resp.get("orderID", "")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_usdc_balance(self):
        if self.simulation_mode:
            return CONFIG.total_bankroll_usdc
        try:
            return float(self.client.get_balance())
        except:
            return 0.0


class FootballDataClient:
    def __init__(self, config: BotConfig):
        self.odds_api_key = config.odds_api_key
        self.sportradar_key = config.sportradar_key

    def get_upcoming_matches(self) -> List[Match]:
        if not self.odds_api_key:
            log.warning("No ODDS_API_KEY set. Using mock data.")
            return self._mock_upcoming_matches()
        try:
            leagues = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_brazil_campeonato"]
            matches = []
            for league in leagues:
                params = {"apiKey": self.odds_api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"}
                resp = requests.get("https://api.the-odds-api.com/v4/sports/" + league + "/odds/", params=params, timeout=10)
                if resp.status_code != 200:
                    continue
                for game in resp.json():
                    m = self._parse(game)
                    if m:
                        matches.append(m)
            log.info("[INFO] Found " + str(len(matches)) + " upcoming matches")
            return matches
        except Exception as e:
            log.error("Error fetching odds: " + str(e))
            return self._mock_upcoming_matches()

    def _parse(self, game) -> Optional[Match]:
        try:
            start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
            bk = game.get("bookmakers", [])
            if not bk:
                return None
            outcomes = bk[0]["markets"][0]["outcomes"]
            odds_map = {o["name"]: 1 / o["price"] for o in outcomes}
            home = game["home_team"]
            away = game["away_team"]
            return Match(match_id=game["id"], home_team=home, away_team=away, start_time=start,
                         league=game.get("sport_title", "Football"),
                         home_odds=odds_map.get(home, 0.4), draw_odds=odds_map.get("Draw", 0.3), away_odds=odds_map.get(away, 0.3))
        except:
            return None

    def get_live_score(self, match: Match) -> Tuple[int, int, int, str]:
        if not self.sportradar_key:
            return self._mock_live_score(match)
        try:
            resp = requests.get("https://api.sportradar.com/soccer/trial/v4/en/matches/" + match.match_id + "/timeline.json",
                                params={"api_key": self.sportradar_key}, timeout=5)
            s = resp.json().get("sport_event_status", {})
            return s.get("match_time", 0), s.get("home_score", 0), s.get("away_score", 0), s.get("status", "live")
        except:
            return self._mock_live_score(match)

    def _mock_upcoming_matches(self) -> List[Match]:
        now = datetime.utcnow()
        return [
            Match(match_id="mock_1", home_team="Arsenal", away_team="Chelsea",
                  start_time=now + timedelta(hours=3), league="Premier League",
                  home_win_token_id="mock_token_home_1", home_odds=0.45, draw_odds=0.28, away_odds=0.27),
            Match(match_id="mock_2", home_team="Barcelona", away_team="Real Madrid",
                  start_time=now + timedelta(hours=26), league="La Liga",
                  home_win_token_id="mock_token_home_2", home_odds=0.50, draw_odds=0.25, away_odds=0.25),
        ]

    def _mock_live_score(self, match: Match) -> Tuple[int, int, int, str]:
        elapsed = (datetime.utcnow() - match.start_time).total_seconds() / 60
        minute = max(0, min(90, int(elapsed)))
        if minute < 1:
            return 0, 0, 0, "not_started"
        if minute >= 90:
            return 90, 1, 0, "finished"
        return minute, (1 if minute > 35 else 0), 0, "live"


class StrategyEngine:
    def __init__(self, config: BotConfig):
        self.config = config

    def should_enter(self, match: Match, available_usdc: float) -> Tuple[bool, str, float]:
        now = datetime.utcnow()
        hours_until = (match.start_time.replace(tzinfo=None) - now).total_seconds() / 3600
        if not (self.config.min_hours_before_game <= hours_until <= self.config.max_hours_before_game):
            return False, "", 0

        total = match.home_odds + match.draw_odds + match.away_odds
        if total <= 0:
            return False, "", 0

        best_edge = 0
        best_outcome = ""
        for outcome, market_price in [("home", match.home_odds), ("away", match.away_odds)]:
            if market_price <= 0:
                continue
            model_prob = market_price / total
            edge = model_prob - market_price
            if 0.03 < edge < 0.25 and edge > best_edge:
                best_edge = edge
                best_outcome = outcome

        if best_outcome:
            log.info("[EDGE] " + match.home_team + " vs " + match.away_team + " | " + best_outcome + " | " + str(round(best_edge * 100, 1)) + "%")
            return True, best_outcome, best_edge
        return False, "", 0

    def calculate_position_size(self, available_usdc: float) -> float:
        return round(min(self.config.max_position_usdc, available_usdc * self.config.bankroll_risk_pct), 2)

    def should_exit(self, position: Position, match: Match, current_price: float) -> Tuple[bool, str]:
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        if pnl_pct >= self.config.profit_target_pct:
            return True, "profit_target (+" + str(round(pnl_pct * 100, 1)) + "%)"
        if pnl_pct <= -self.config.stop_loss_pct:
            return True, "stop_loss (" + str(round(pnl_pct * 100, 1)) + "%)"
        if match.minute >= self.config.sell_after_minutes:
            return True, "time_stop (min " + str(match.minute) + ")"
        if match.status == "live":
            if self.config.sell_on_favorable_goal and pnl_pct > 0.05:
                if position.outcome == "home" and match.home_score > match.away_score:
                    return True, "favorable_goal (" + str(match.home_score) + "-" + str(match.away_score) + ")"
                if position.outcome == "away" and match.away_score > match.home_score:
                    return True, "favorable_goal (" + str(match.home_score) + "-" + str(match.away_score) + ")"
            if self.config.sell_on_adverse_goal:
                if position.outcome == "home" and match.away_score > match.home_score:
                    return True, "adverse_goal (" + str(match.home_score) + "-" + str(match.away_score) + ")"
                if position.outcome == "away" and match.home_score > match.away_score:
                    return True, "adverse_goal (" + str(match.home_score) + "-" + str(match.away_score) + ")"
        if match.status == "finished":
            return True, "match_finished"
        return False, ""


class PortfolioManager:
    def __init__(self):
        self.positions: dict = {}
        self.closed_positions: list = []
        self.total_pnl: float = 0.0
        self._load_state()

    def add_position(self, position: Position):
        self.positions[position.position_id] = position
        self._save_state()

    def close_position(self, position_id: str, exit_price: float, reason: str):
        if position_id not in self.positions:
            return
        pos = self.positions.pop(position_id)
        pos.status = "sold"
        pos.exit_price = exit_price
        pos.pnl_usdc = (exit_price - pos.entry_price) * pos.shares
        pos.sell_reason = reason
        self.total_pnl += pos.pnl_usdc
        self.closed_positions.append(pos)
        log.info("[SELL] Closed | PnL: " + str(round(pos.pnl_usdc, 2)) + " USDC | " + reason)
        self._save_state()

    def get_stats(self) -> dict:
        wins = [p for p in self.closed_positions if p.pnl_usdc > 0]
        losses = [p for p in self.closed_positions if p.pnl_usdc <= 0]
        return {
            "open_positions": len(self.positions),
            "closed_positions": len(self.closed_positions),
            "total_pnl_usdc": round(self.total_pnl, 2),
            "win_rate": len(wins) / len(self.closed_positions) if self.closed_positions else 0,
            "wins": len(wins), "losses": len(losses),
        }

    def _save_state(self):
        try:
            with open("portfolio_state.json", "w") as f:
                json.dump({"positions": {k: asdict(v) for k, v in self.positions.items()},
                           "total_pnl": self.total_pnl}, f, indent=2, default=str)
        except Exception as e:
            log.debug("Save error: " + str(e))

    def _load_state(self):
        try:
            if os.path.exists("portfolio_state.json"):
                with open("portfolio_state.json") as f:
                    state = json.load(f)
                self.total_pnl = state.get("total_pnl", 0.0)
                log.info("[LOAD] Portfolio loaded | PnL: " + str(round(self.total_pnl, 2)) + " USDC")
        except Exception as e:
            log.debug("Load error: " + str(e))


class PolymarketFootballBot:
    def __init__(self):
        self.config = CONFIG
        self.poly = PolymarketClient(CONFIG)
        self.football = FootballDataClient(CONFIG)
        self.strategy = StrategyEngine(CONFIG)
        self.portfolio = PortfolioManager()
        self.running = False
        self._tracked_matches: dict = {}
        mode = "[SIMULATION]" if CONFIG.simulation_mode else "[LIVE TRADING]"
        log.info("=" * 60)
        log.info("  POLYMARKET FOOTBALL BOT STARTED " + mode)
        log.info("  Bankroll: $" + str(CONFIG.total_bankroll_usdc) + " USDC")
        log.info("=" * 60)

    def scan_pregame(self):
        log.info("[SCAN] Scanning for pre-game opportunities...")
        if len(self.portfolio.positions) >= self.config.max_open_positions:
            log.info("[WAIT] Max open positions reached")
            return

        balance = self.poly.get_usdc_balance()
        for match in self.football.get_upcoming_matches():
            if match.match_id in self._tracked_matches:
                continue
            should_enter, outcome, score = self.strategy.should_enter(match, balance)
            if not should_enter:
                continue

            token_id = self._get_token(match, outcome)
            current_price = self.poly.get_mid_price(token_id) or (match.home_odds if outcome == "home" else match.away_odds)
            size_usdc = self.strategy.calculate_position_size(balance)
            result = self.poly.place_buy_order(token_id, size_usdc, current_price)

            if result["success"]:
                pos = Position(
                    position_id=result["order_id"], match=match, outcome=outcome,
                    token_id=token_id, entry_price=current_price, size_usdc=size_usdc,
                    shares=size_usdc / current_price, entry_time=datetime.utcnow(),
                )
                self.portfolio.add_position(pos)
                self._tracked_matches[match.match_id] = match
                log.info("[BUY] " + match.home_team + " vs " + match.away_team + " | " + outcome + " | $" + str(size_usdc))

                telegram(
                    "<b>[COMPRA]</b> " + match.home_team + " vs " + match.away_team + "\n" +
                    "Aposta: <b>" + outcome.upper() + "</b>\n" +
                    "Valor: $" + str(size_usdc) + " USDC\n" +
                    "Preco: " + str(round(current_price, 4)) + "\n" +
                    "Liga: " + match.league
                )

    def monitor_live(self):
        if not self.portfolio.positions:
            return
        log.info("[LIVE] Monitoring " + str(len(self.portfolio.positions)) + " positions...")
        to_close = []

        for pos_id, position in list(self.portfolio.positions.items()):
            match = position.match
            minute, hs, as_, status = self.football.get_live_score(match)
            match.minute, match.home_score, match.away_score, match.status = minute, hs, as_, status

            current_price = self.poly.get_mid_price(position.token_id) or position.entry_price
            pnl_pct = (current_price - position.entry_price) / position.entry_price
            log.info("  [MATCH] " + match.home_team + " " + str(hs) + "-" + str(as_) + " " + match.away_team +
                     " [" + str(minute) + "'] PnL: " + str(round(pnl_pct * 100, 1)) + "%")

            should_exit, reason = self.strategy.should_exit(position, match, current_price)
            if should_exit:
                to_close.append((pos_id, current_price, reason))

        for pos_id, price, reason in to_close:
            position = self.portfolio.positions.get(pos_id)
            if not position:
                continue
            result = self.poly.place_sell_order(position.token_id, position.shares, price)
            if result["success"]:
                pnl = (price - position.entry_price) * position.shares
                self.portfolio.close_position(pos_id, price, reason)
                resultado = "LUCRO" if pnl >= 0 else "PERDA"
                telegram(
                    "<b>[" + resultado + "]</b> " + position.match.home_team + " vs " + position.match.away_team + "\n" +
                    "Aposta: " + position.outcome.upper() + "\n" +
                    "Motivo: " + reason + "\n" +
                    "PnL: $" + str(round(pnl, 2)) + " USDC\n" +
                    "Placar: " + str(position.match.home_score) + "-" + str(position.match.away_score)
                )

    def _get_token(self, match: Match, outcome: str) -> str:
        if outcome == "home":
            return match.home_win_token_id or "mock_token_" + match.match_id + "_home"
        elif outcome == "draw":
            return match.draw_token_id or "mock_token_" + match.match_id + "_draw"
        return match.away_win_token_id or "mock_token_" + match.match_id + "_away"

    def print_status(self):
        stats = self.portfolio.get_stats()
        balance = self.poly.get_usdc_balance()
        log.info("=" * 48)
        log.info("               BOT STATUS")
        log.info("=" * 48)
        log.info("  Balance:   $" + str(round(balance, 2)) + " USDC")
        log.info("  Open:      " + str(stats["open_positions"]))
        log.info("  Closed:    " + str(stats["closed_positions"]))
        log.info("  PnL:       $" + str(stats["total_pnl_usdc"]) + " USDC")
        if stats["closed_positions"] > 0:
            log.info("  Win rate:  " + str(round(stats["win_rate"] * 100, 1)) + "% (" + str(stats["wins"]) + "W/" + str(stats["losses"]) + "L)")
        log.info("=" * 48)

        telegram(
            "<b>[STATUS]</b> PolyBot\n" +
            "Balance: $" + str(round(balance, 2)) + " USDC\n" +
            "Abertas: " + str(stats["open_positions"]) + " | Fechadas: " + str(stats["closed_positions"]) + "\n" +
            "PnL: $" + str(stats["total_pnl_usdc"]) + " USDC (" + str(stats["wins"]) + "W/" + str(stats["losses"]) + "L)"
        )

    def start(self):
        self.running = True
        log.info("[START] Bot started!")
        telegram(
            "<b>[START] PolyBot iniciado!</b>\n" +
            "Modo: SIMULACAO\n" +
            "Bankroll: $" + str(CONFIG.total_bankroll_usdc) + " USDC\n" +
            "Max aposta: $" + str(CONFIG.max_position_usdc) + " USDC"
        )
        schedule.every(30).minutes.do(self.scan_pregame)
        schedule.every(60).seconds.do(self.monitor_live)
        schedule.every(10).minutes.do(self.print_status)
        self.scan_pregame()
        self.print_status()
        while self.running:
            schedule.run_pending()
            time.sleep(5)

    def stop(self):
        self.running = False
        log.info("[STOP] Bot stopped.")
        self.print_status()


if __name__ == "__main__":
    import sys
    if not CONFIG.simulation_mode:
        print("\n!!! WARNING: LIVE TRADING MODE ACTIVE !!!")
        confirm = input("Type CONFIRM to proceed: ").strip()
        if confirm != "CONFIRM":
            sys.exit(0)

    bot = PolymarketFootballBot()
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
