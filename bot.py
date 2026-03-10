"""
=================================================================
         POLYMARKET FOOTBALL BOT - Automatic Trading Agent
   Strategy: Pre-game buy + In-game sell on events (goals)
=================================================================

SETUP:
  pip install py-clob-client web3 requests python-dotenv websocket-client schedule

REQUIRED ENV VARS (.env file):
  POLYMARKET_API_KEY=your_api_key
  POLYMARKET_API_SECRET=your_api_secret
  POLYMARKET_API_PASSPHRASE=your_passphrase
  POLYMARKET_PRIVATE_KEY=your_wallet_private_key   # Polygon wallet
  ODDS_API_KEY=your_theoddsapi_key                 # https://the-odds-api.com
  SPORTRADAR_API_KEY=your_sportradar_key           # For live events (optional)
"""

import os
import json
import time
import logging
import schedule
import threading
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

# Polymarket CLOB client
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType, Side
    from py_clob_client.constants import POLYGON
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("[WARNING] py-clob-client not installed. Running in SIMULATION mode.")

load_dotenv()

# 
#  LOGGING
# 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("PolyBot")


# 
#  CONFIGURATION
# 
@dataclass
class BotConfig:
    # Capital management
    max_position_usdc: float = 50.0          # Max USDC per bet
    max_open_positions: int = 5              # Max simultaneous bets
    total_bankroll_usdc: float = 500.0       # Total bankroll
    bankroll_risk_pct: float = 0.05          # Risk 5% per bet

    # Entry filters (pre-game)
    min_odds: float = 0.25                   # Min probability (25%)
    max_odds: float = 0.75                   # Max probability (75%)
    min_liquidity_usdc: float = 1000.0       # Min market liquidity
    min_hours_before_game: float = 1.0       # Open position at least 1h before
    max_hours_before_game: float = 48.0      # Max 48h before game

    # Exit strategy (in-game events)
    sell_on_favorable_goal: bool = True      # Sell when team we bet on scores
    sell_on_adverse_goal: bool = True        # Cut loss when opponent scores
    profit_target_pct: float = 0.30          # Take profit at +30%
    stop_loss_pct: float = 0.40              # Stop loss at -40%
    sell_after_minutes: int = 70             # Force sell at minute 70+

    # Polymarket API
    host: str = "https://clob.polymarket.com"
    chain_id: int = POLYGON if CLOB_AVAILABLE else 137

    # Live data
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    sportradar_key: str = field(default_factory=lambda: os.getenv("SPORTRADAR_API_KEY", ""))

    # Simulation mode (no real money)
    simulation_mode: bool = True  # Set to False for live trading!


CONFIG = BotConfig()


# 
#  DATA MODELS
# 
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
    # Live data
    minute: int = 0
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"  # scheduled | live | finished


@dataclass
class Position:
    position_id: str
    match: Match
    outcome: str           # "home" | "draw" | "away"
    token_id: str
    entry_price: float
    size_usdc: float
    shares: float
    entry_time: datetime
    status: str = "open"   # open | sold | expired
    exit_price: float = 0.0
    pnl_usdc: float = 0.0
    sell_reason: str = ""


# 
#  POLYMARKET CLIENT WRAPPER
# 
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
            log.error(f"Failed to init Polymarket client: {e}")
            self.simulation_mode = True

    def get_football_markets(self) -> list[dict]:
        """Fetch active football markets from Polymarket"""
        try:
            url = "https://gamma-api.polymarket.com/markets"
            params = {
                "active": "true",
                "closed": "false",
                "tag_slug": "soccer",
                "limit": 100
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
            log.info(f"[INFO] Found {len(markets)} football markets")
            return markets
        except Exception as e:
            log.error(f"Error fetching markets: {e}")
            return []

    def get_market_orderbook(self, token_id: str) -> dict:
        """Get current orderbook for a token"""
        try:
            url = f"https://clob.polymarket.com/book?token_id={token_id}"
            resp = requests.get(url, timeout=5)
            return resp.json()
        except Exception as e:
            log.error(f"Error fetching orderbook: {e}")
            return {}

    def get_mid_price(self, token_id: str) -> float:
        """Get mid price from orderbook"""
        book = self.get_market_orderbook(token_id)
        try:
            best_bid = float(book["bids"][0]["price"]) if book.get("bids") else 0
            best_ask = float(book["asks"][0]["price"]) if book.get("asks") else 1
            return (best_bid + best_ask) / 2
        except:
            return 0.0

    def place_buy_order(self, token_id: str, size_usdc: float, price: float) -> dict:
        """Place a buy (YES) order"""
        if self.simulation_mode:
            sim_id = f"SIM-{int(time.time())}"
            log.info(f"[SIM] BUY {size_usdc:.2f} USDC @ {price:.4f} | token={token_id[:12]}...")
            return {"success": True, "order_id": sim_id, "simulated": True}

        try:
            shares = size_usdc / price
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=Side.BUY,
                token_id=token_id,
            )
            resp = self.client.create_and_post_order(order_args)
            log.info(f"[OK] BUY order placed: {resp}")
            return {"success": True, "order_id": resp.get("orderID", ""), "response": resp}
        except Exception as e:
            log.error(f"[ERROR] BUY order failed: {e}")
            return {"success": False, "error": str(e)}

    def place_sell_order(self, token_id: str, shares: float, price: float) -> dict:
        """Place a sell order"""
        if self.simulation_mode:
            sim_id = f"SIM-SELL-{int(time.time())}"
            log.info(f"[SIM] SELL {shares:.4f} shares @ {price:.4f} | token={token_id[:12]}...")
            return {"success": True, "order_id": sim_id, "simulated": True}

        try:
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=Side.SELL,
                token_id=token_id,
            )
            resp = self.client.create_and_post_order(order_args)
            log.info(f"[OK] SELL order placed: {resp}")
            return {"success": True, "order_id": resp.get("orderID", ""), "response": resp}
        except Exception as e:
            log.error(f"[ERROR] SELL order failed: {e}")
            return {"success": False, "error": str(e)}

    def get_usdc_balance(self) -> float:
        """Get wallet USDC balance"""
        if self.simulation_mode:
            return CONFIG.total_bankroll_usdc
        try:
            balance = self.client.get_balance()
            return float(balance)
        except:
            return 0.0


# 
#  LIVE FOOTBALL DATA
# 
class FootballDataClient:
    """
    Fetches live football scores and events.
    Uses The Odds API for pre-game odds.
    Uses Sportradar (or API-Football) for live scores.
    """
    def __init__(self, config: BotConfig):
        self.config = config
        self.odds_api_key = config.odds_api_key
        self.sportradar_key = config.sportradar_key

    def get_upcoming_matches(self) -> list[Match]:
        """Get upcoming football matches with odds"""
        if not self.odds_api_key:
            log.warning("No ODDS_API_KEY set. Using mock data.")
            return self._mock_upcoming_matches()

        try:
            url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
            params = {
                "apiKey": self.odds_api_key,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso"
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            matches = []
            for game in data:
                match = self._parse_odds_api_game(game)
                if match:
                    matches.append(match)
            log.info(f"[INFO] Found {len(matches)} upcoming matches")
            return matches
        except Exception as e:
            log.error(f"Error fetching odds: {e}")
            return self._mock_upcoming_matches()

    def _parse_odds_api_game(self, game: dict) -> Optional[Match]:
        try:
            start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                return None
            outcomes = bookmakers[0]["markets"][0]["outcomes"]
            odds_map = {o["name"]: 1 / o["price"] for o in outcomes}
            home = game["home_team"]
            away = game["away_team"]
            return Match(
                match_id=game["id"],
                home_team=home,
                away_team=away,
                start_time=start,
                league=game.get("sport_title", "Football"),
                home_odds=odds_map.get(home, 0.4),
                draw_odds=odds_map.get("Draw", 0.3),
                away_odds=odds_map.get(away, 0.3),
            )
        except Exception as e:
            log.debug(f"Parse error: {e}")
            return None

    def get_live_score(self, match: Match) -> tuple[int, int, int, str]:
        """Returns (minute, home_score, away_score, status)"""
        if not self.sportradar_key:
            return self._mock_live_score(match)

        try:
            url = f"https://api.sportradar.com/soccer/trial/v4/en/matches/{match.match_id}/timeline.json"
            params = {"api_key": self.sportradar_key}
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            sport_event = data.get("sport_event_status", {})
            return (
                sport_event.get("match_time", 0),
                sport_event.get("home_score", 0),
                sport_event.get("away_score", 0),
                sport_event.get("status", "live")
            )
        except Exception as e:
            log.debug(f"Live score error: {e}")
            return self._mock_live_score(match)

    def _mock_upcoming_matches(self) -> list[Match]:
        """Mock data for testing"""
        now = datetime.utcnow()
        return [
            Match(
                match_id="mock_1",
                home_team="Arsenal",
                away_team="Chelsea",
                start_time=now + timedelta(hours=3),
                league="Premier League",
                home_win_token_id="mock_token_home_1",
                home_odds=0.45,
                draw_odds=0.28,
                away_odds=0.27,
            ),
            Match(
                match_id="mock_2",
                home_team="Barcelona",
                away_team="Real Madrid",
                start_time=now + timedelta(hours=26),
                league="La Liga",
                home_win_token_id="mock_token_home_2",
                home_odds=0.50,
                draw_odds=0.25,
                away_odds=0.25,
            ),
        ]

    def _mock_live_score(self, match: Match) -> tuple[int, int, int, str]:
        """Simulate live match for testing"""
        elapsed = (datetime.utcnow() - match.start_time).total_seconds() / 60
        minute = max(0, min(90, int(elapsed)))
        if minute < 1:
            return 0, 0, 0, "not_started"
        if minute >= 90:
            return 90, 1, 0, "finished"
        # Simulate a goal at minute 35
        home_score = 1 if minute > 35 else 0
        return minute, home_score, 0, "live"


# 
#  STRATEGY ENGINE
# 
class StrategyEngine:
    def __init__(self, config: BotConfig):
        self.config = config

        # Edge thresholds
        self.min_edge = 0.05
        self.max_edge = 0.25

    def model_probability(self, match: Match) -> dict:
        """
        Modelo simples baseado nas odds das casas.
        Converte odds em probabilidade normalizada.
        """

        home = match.home_odds
        draw = match.draw_odds
        away = match.away_odds

        total = home + draw + away

        if total <= 0:
            return {"home": 0.33, "draw": 0.33, "away": 0.33}

        return {
            "home": home / total,
            "draw": draw / total,
            "away": away / total
        }

    def calculate_edge(self, model_prob: float, market_price: float) -> float:
        """
        EDGE = probabilidade modelo - preço do mercado
        """
        return model_prob - market_price

    def should_enter(self, match: Match, available_usdc: float):

        now = datetime.utcnow()

        hours_until = (match.start_time.replace(tzinfo=None) - now).total_seconds() / 3600

        if hours_until < self.config.min_hours_before_game:
            return False, "", 0

        if hours_until > self.config.max_hours_before_game:
            return False, "", 0

        model_probs = self.model_probability(match)

        best_edge = 0
        best_outcome = ""

        outcomes = [
            ("home", match.home_odds, match.home_win_token_id),
            ("away", match.away_odds, match.away_win_token_id),
        ]

        for outcome, market_price, token in outcomes:

            if market_price <= 0:
                continue

            model_prob = model_probs[outcome]

            edge = self.calculate_edge(model_prob, market_price)

            if self.min_edge < edge < self.max_edge:

                if edge > best_edge:
                    best_edge = edge
                    best_outcome = outcome

        if best_outcome:

            log.info(
                f"[EDGE SIGNAL] {match.home_team} vs {match.away_team} | "
                f"Outcome: {best_outcome} | Edge: {best_edge:.2%}"
            )

            return True, best_outcome, best_edge

        return False, "", 0

    def calculate_position_size(self, available_usdc: float):

        size = min(
            self.config.max_position_usdc,
            available_usdc * self.config.bankroll_risk_pct
        )

        return round(size, 2)

    def should_exit(self, position: Position, match: Match, current_price: float):

        pnl_pct = (current_price - position.entry_price) / position.entry_price

        # Take profit
        if pnl_pct >= self.config.profit_target_pct:
            return True, f"profit_target (+{pnl_pct*100:.1f}%)"

        # Stop loss
        if pnl_pct <= -self.config.stop_loss_pct:
            return True, f"stop_loss ({pnl_pct*100:.1f}%)"

        # Time exit
        if match.minute >= self.config.sell_after_minutes:
            return True, f"time_stop (min {match.minute})"

        # Goal events
        if match.status == "live":

            if self.config.sell_on_favorable_goal:

                if position.outcome == "home" and match.home_score > match.away_score:
                    if pnl_pct > 0.05:
                        return True, "favorable_goal"

                if position.outcome == "away" and match.away_score > match.home_score:
                    if pnl_pct > 0.05:
                        return True, "favorable_goal"

            if self.config.sell_on_adverse_goal:

                if position.outcome == "home" and match.away_score > match.home_score:
                    return True, "adverse_goal"

                if position.outcome == "away" and match.home_score > match.away_score:
                    return True, "adverse_goal"

        if match.status == "finished":
            return True, "match_finished"

        return False, ""

        #  PROFIT TARGET 
        if pnl_pct >= self.config.profit_target_pct:
            return True, f"profit_target (+{pnl_pct*100:.1f}%)"

        #  STOP LOSS 
        if pnl_pct <= -self.config.stop_loss_pct:
            return True, f"stop_loss ({pnl_pct*100:.1f}%)"

        #  TIME STOP 
        if match.minute >= self.config.sell_after_minutes:
            return True, f"time_stop (min {match.minute})"

        #  GOAL EVENTS 
        if match.status == "live":
            # Sell on favorable goal (we're winning  lock profit)
            if self.config.sell_on_favorable_goal:
                if position.outcome == "home" and match.home_score > match.away_score:
                    if pnl_pct > 0.05:  # Only sell if we have profit
                        return True, f"favorable_goal (score: {match.home_score}-{match.away_score})"
                elif position.outcome == "away" and match.away_score > match.home_score:
                    if pnl_pct > 0.05:
                        return True, f"favorable_goal (score: {match.home_score}-{match.away_score})"

            # Cut on adverse goal (opponent scores  exit)
            if self.config.sell_on_adverse_goal:
                if position.outcome == "home" and match.away_score > match.home_score:
                    return True, f"adverse_goal (score: {match.home_score}-{match.away_score})"
                elif position.outcome == "away" and match.home_score > match.away_score:
                    return True, f"adverse_goal (score: {match.home_score}-{match.away_score})"

        #  MATCH FINISHED 
        if match.status == "finished":
            return True, "match_finished"

        return False, ""


# 
#  PORTFOLIO MANAGER
# 
class PortfolioManager:
    def __init__(self):
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
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
        log.info(f"[SELL] Position closed | PnL: {pos.pnl_usdc:+.2f} USDC | Reason: {reason}")
        self._save_state()

    def get_stats(self) -> dict:
        wins = [p for p in self.closed_positions if p.pnl_usdc > 0]
        losses = [p for p in self.closed_positions if p.pnl_usdc <= 0]
        return {
            "open_positions": len(self.positions),
            "closed_positions": len(self.closed_positions),
            "total_pnl_usdc": round(self.total_pnl, 2),
            "win_rate": len(wins) / len(self.closed_positions) if self.closed_positions else 0,
            "wins": len(wins),
            "losses": len(losses),
        }

    def _save_state(self):
        try:
            state = {
                "positions": {k: asdict(v) for k, v in self.positions.items()},
                "total_pnl": self.total_pnl,
                "closed_count": len(self.closed_positions),
            }
            with open("portfolio_state.json", "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            log.debug(f"Save state error: {e}")

    def _load_state(self):
        try:
            if os.path.exists("portfolio_state.json"):
                with open("portfolio_state.json") as f:
                    state = json.load(f)
                self.total_pnl = state.get("total_pnl", 0.0)
                log.info(f"[LOAD] Portfolio loaded | PnL: {self.total_pnl:+.2f} USDC")
        except Exception as e:
            log.debug(f"Load state error: {e}")


# 
#  MAIN BOT
# 
class PolymarketFootballBot:
    def __init__(self):
        self.config = CONFIG
        self.poly = PolymarketClient(CONFIG)
        self.football = FootballDataClient(CONFIG)
        self.strategy = StrategyEngine(CONFIG)
        self.portfolio = PortfolioManager()
        self.running = False
        self._tracked_matches: dict[str, Match] = {}

        mode = "[SIMULATION]" if CONFIG.simulation_mode else "[LIVE TRADING]"
        log.info("=" * 60)
        log.info(f"  POLYMARKET FOOTBALL BOT STARTED {mode}")
        log.info(f"  Bankroll: ${CONFIG.total_bankroll_usdc:.0f} USDC")
        log.info(f"  Max position: ${CONFIG.max_position_usdc:.0f} USDC")
        log.info("=" * 60)

    #  SCAN FOR NEW BETS 
    def scan_pregame(self):
        log.info("[SCAN] Scanning for pre-game opportunities...")

        if len(self.portfolio.positions) >= self.config.max_open_positions:
            log.info("[WAIT] Max open positions reached, skipping scan")
            return

        balance = self.poly.get_usdc_balance()
        matches = self.football.get_upcoming_matches()

        for match in matches:
            if match.match_id in self._tracked_matches:
                continue  # Already tracking

            should_enter, outcome, score = self.strategy.should_enter(match, balance)

            if not should_enter:
                continue

            # Get token ID based on outcome
            token_id = self._get_token_for_outcome(match, outcome)
            if not token_id:
                log.warning(f"No token ID for {match.home_team} vs {match.away_team} ({outcome})")
                continue

            # Get current price
            current_price = self.poly.get_mid_price(token_id)
            if current_price <= 0:
                current_price = match.home_odds if outcome == "home" else match.away_odds

            # Calculate size
            size_usdc = self.strategy.calculate_position_size(balance)

            # Place order
            result = self.poly.place_buy_order(token_id, size_usdc, current_price)

            if result["success"]:
                shares = size_usdc / current_price
                position = Position(
                    position_id=result["order_id"],
                    match=match,
                    outcome=outcome,
                    token_id=token_id,
                    entry_price=current_price,
                    size_usdc=size_usdc,
                    shares=shares,
                    entry_time=datetime.utcnow(),
                )
                self.portfolio.add_position(position)
                self._tracked_matches[match.match_id] = match
                log.info(
                    f"[BUY] NEW POSITION | {match.home_team} vs {match.away_team} | "
                    f"Outcome: {outcome} | Size: ${size_usdc:.2f} | Price: {current_price:.4f}"
                )

    #  MONITOR LIVE POSITIONS 
    def monitor_live(self):
        if not self.portfolio.positions:
            return

        log.info(f"[LIVE] Monitoring {len(self.portfolio.positions)} open positions...")

        to_close = []

        for pos_id, position in list(self.portfolio.positions.items()):
            match = position.match

            # Get live score
            minute, home_score, away_score, status = self.football.get_live_score(match)
            match.minute = minute
            match.home_score = home_score
            match.away_score = away_score
            match.status = status

            # Get current market price
            current_price = self.poly.get_mid_price(position.token_id)
            if current_price <= 0:
                current_price = position.entry_price  # Fallback

            pnl_pct = (current_price - position.entry_price) / position.entry_price
            log.info(
                f"  [MATCH] {match.home_team} {home_score}-{away_score} {match.away_team} "
                f"[{minute}'] | PnL: {pnl_pct:+.1%} | Price: {current_price:.4f}"
            )

            # Check exit condition
            should_exit, reason = self.strategy.should_exit(position, match, current_price)

            if should_exit:
                to_close.append((pos_id, current_price, reason))

        # Execute sells
        for pos_id, price, reason in to_close:
            position = self.portfolio.positions.get(pos_id)
            if not position:
                continue
            result = self.poly.place_sell_order(position.token_id, position.shares, price)
            if result["success"]:
                self.portfolio.close_position(pos_id, price, reason)

    #  GET TOKEN ID FOR OUTCOME 
    def _get_token_for_outcome(self, match: Match, outcome: str) -> str:
        if outcome == "home":
            return match.home_win_token_id or f"mock_token_{match.match_id}_home"
        elif outcome == "draw":
            return match.draw_token_id or f"mock_token_{match.match_id}_draw"
        elif outcome == "away":
            return match.away_win_token_id or f"mock_token_{match.match_id}_away"
        return ""

    #  PRINT STATUS 
    def print_status(self):
        stats = self.portfolio.get_stats()
        balance = self.poly.get_usdc_balance()
        log.info(f"")
        log.info("================================================")
        log.info("               BOT STATUS                      ")
        log.info("================================================")
        log.info(f"  Balance:        ${balance:.2f} USDC")
        log.info(f"  Open positions: {stats['open_positions']}")
        log.info(f"  Closed:         {stats['closed_positions']}")
        log.info(f"  Total PnL:      ${stats['total_pnl_usdc']:+.2f} USDC")
        if stats['closed_positions'] > 0:
            log.info(f"  Win rate:       {stats['win_rate']:.1%} ({stats['wins']}W / {stats['losses']}L)")
        log.info("================================================")
        log.info(f"")

    #  MAIN LOOP 
    def start(self):
        self.running = True
        log.info("[START] Bot started!")

        # Schedule tasks
        schedule.every(30).minutes.do(self.scan_pregame)   # Scan every 30 min
        schedule.every(60).seconds.do(self.monitor_live)   # Monitor every 60s
        schedule.every(10).minutes.do(self.print_status)   # Status every 10 min

        # Run immediately on start
        self.scan_pregame()
        self.print_status()

        while self.running:
            schedule.run_pending()
            time.sleep(5)

    def stop(self):
        self.running = False
        log.info("[STOP] Bot stopped.")
        self.print_status()


# 
#  ENTRY POINT
# 
if __name__ == "__main__":
    import sys

    # Safety check
    if not CONFIG.simulation_mode:
        print("\n!!! WARNING: LIVE TRADING MODE ACTIVE !!!")
        print("Real money will be used. Type 'CONFIRM' to proceed:")
        confirm = input("> ").strip()
        if confirm != "CONFIRM":
            print("Aborted.")
            sys.exit(0)

    bot = PolymarketFootballBot()
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
