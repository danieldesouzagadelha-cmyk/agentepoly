"""
=================================================================
    POLYMARKET FOOTBALL BOT v3.0 - VERSÃO FUNCIONAL
    Busca jogos REAIS da Polymarket via Gamma API
    Modo simulação ativo - SEM riscos
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
from typing import Optional, List, Tuple, Dict, Any
from collections import deque
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("PolyBot")

# ============= CONFIGURAÇÕES =============
@dataclass
class BotConfig:
    """Configurações principais do bot"""
    
    # Gestão de risco
    max_position_usdc: float = 50.0
    max_open_positions: int = 3
    total_bankroll_usdc: float = 500.0
    bankroll_risk_pct: float = 0.05
    
    # Filtros de entrada
    min_edge_pct: float = 0.02
    max_edge_pct: float = 0.30
    min_hours_before_game: float = 1.0
    max_hours_before_game: float = 72.0
    
    # Estratégia de saída
    profit_targets: List[float] = field(default_factory=lambda: [0.20, 0.40])
    stop_losses: List[float] = field(default_factory=lambda: [0.15, 0.30])
    trailing_stop_pct: float = 0.15
    max_hold_minutes: int = 90
    
    # Modo de operação
    simulation_mode: bool = True  # SEMPRE True para testes
    
    # APIs
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    sportradar_key: str = field(default_factory=lambda: os.getenv("SPORTRADAR_API_KEY", ""))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

CONFIG = BotConfig()

# ============= UTILITÁRIOS =============
def send_telegram(message: str):
    """Envia mensagem para Telegram"""
    if not CONFIG.telegram_token or not CONFIG.telegram_chat_id:
        return
    
    try:
        url = f"https://api.telegram.org/bot{CONFIG.telegram_token}/sendMessage"
        payload = {
            "chat_id": CONFIG.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log.debug(f"Telegram error: {e}")

# ============= MODELOS DE DADOS =============
@dataclass
class Match:
    """Representa uma partida de futebol"""
    match_id: str
    home_team: str
    away_team: str
    start_time: datetime
    league: str
    condition_id: str = ""
    token_ids: Dict[str, str] = field(default_factory=dict)
    home_odds: float = 0.0
    draw_odds: float = 0.0
    away_odds: float = 0.0
    minute: int = 0
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"
    
    def __post_init__(self):
        if isinstance(self.start_time, str):
            self.start_time = datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
    
    @property
    def total_odds(self) -> float:
        return self.home_odds + self.draw_odds + self.away_odds
    
    @property
    def normalized_probs(self) -> Dict[str, float]:
        total = self.total_odds
        if total <= 0:
            return {"home": 0.34, "draw": 0.33, "away": 0.33}
        return {
            "home": self.home_odds / total,
            "draw": self.draw_odds / total,
            "away": self.away_odds / total
        }
    
    @property
    def time_until(self) -> float:
        now = datetime.utcnow()
        start = self.start_time.replace(tzinfo=None)
        return (start - now).total_seconds() / 3600
    
    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

@dataclass
class Position:
    """Representa uma posição aberta"""
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
    highest_price: float = 0.0
    
    def __post_init__(self):
        if isinstance(self.entry_time, str):
            self.entry_time = datetime.fromisoformat(self.entry_time)
        self.highest_price = self.entry_price

# ============= CLIENTE POLYMARKET =============
class PolymarketClient:
    """Cliente para API da Polymarket"""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.simulation_mode = config.simulation_mode
        log.info(f"[POLY] Modo: {'SIMULAÇÃO' if self.simulation_mode else 'REAL'}")
    
    def get_mid_price(self, token_id: str) -> float:
        """Obtém preço médio de um token"""
        if self.simulation_mode or not token_id:
            return 0.5
        
        try:
            url = f"{self.clob_url}/book"
            response = requests.get(url, params={"token_id": token_id}, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                
                if bids and asks:
                    best_bid = float(bids[0].get("price", 0))
                    best_ask = float(asks[0].get("price", 1))
                    return (best_bid + best_ask) / 2
        except Exception as e:
            log.debug(f"Erro ao buscar preço: {e}")
        
        return 0.5
    
    def place_order(self, token_id: str, size_usdc: float, side: str, order_type: str = "market") -> Dict:
        """Simula uma ordem (modo simulação)"""
        if self.simulation_mode:
            price = 0.5
            shares = size_usdc / price
            log.info(f"[SIM] {side.upper()} ${size_usdc:.2f} @ {price:.3f}")
            return {
                "success": True,
                "order_id": f"SIM-{int(time.time())}",
                "price": price,
                "shares": shares
            }
        
        # Implementação real quando sair da simulação
        return {"success": False, "error": "Modo real não implementado"}

# ============= CLIENTE DE DADOS DE FUTEBOL =============
class FootballDataClient:
    """Cliente para dados de futebol - VERSÃO FUNCIONAL"""
    
    # Tags de futebol que funcionam no Polymarket
    SOCCER_TAGS = {
        "premier-league": "Premier League",
        "laliga": "La Liga",
        "bundesliga": "Bundesliga",
        "serie-a": "Serie A",
        "ligue-1": "Ligue 1",
        "champions-league": "Champions League",
        "europa-league": "Europa League",
        "brazil-serie-a": "Brasileirão",
        "argentina-primera": "Argentine Primera",
        "liga-mx": "Liga MX",
        "copa-libertadores": "Libertadores",
        "copa-sudamericana": "Sudamericana"
    }
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.gamma_url = "https://gamma-api.polymarket.com"
        log.info(f"[FOOTBALL] Inicializado. Monitorando {len(self.SOCCER_TAGS)} ligas")
    
    def get_upcoming_matches(self) -> List[Match]:
        """Busca jogos de futebol da Polymarket"""
        
        all_matches = []
        
        for tag_slug, league_name in self.SOCCER_TAGS.items():
            try:
                # Busca eventos por tag
                url = f"{self.gamma_url}/events"
                params = {
                    "tag_slug": tag_slug,
                    "active": "true",
                    "limit": 10,
                    "order": "start_date"
                }
                
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code != 200:
                    continue
                
                events = response.json()
                
                for event in events:
                    match = self._parse_event(event, league_name)
                    if match:
                        all_matches.append(match)
                        
                        log.info(f"  ✅ {match.home_team} vs {match.away_team} | "
                                f"Início: {match.start_time.strftime('%H:%M %d/%m')}")
                
                # Pequena pausa entre requisições
                time.sleep(0.5)
                
            except Exception as e:
                log.debug(f"Erro na tag {tag_slug}: {e}")
                continue
        
        # Se não encontrou nada, usa dados mockados
        if not all_matches:
            log.warning("Nenhum jogo encontrado. Usando dados simulados.")
            return self._get_mock_matches()
        
        log.info(f"Total: {len(all_matches)} jogos encontrados")
        return all_matches
    
    def _parse_event(self, event: Dict, league: str) -> Optional[Match]:
        """Converte evento em Match"""
        try:
            title = event.get("title", "")
            
            # Extrai times do título
            teams = self._extract_teams(title)
            if not teams:
                return None
            
            home_team, away_team = teams
            
            # Data do evento
            start_date = event.get("start_date")
            if not start_date:
                return None
            
            start_time = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            
            # Pega odds dos markets
            home_odds = 0.5
            draw_odds = 0.28
            away_odds = 0.5
            
            markets = event.get("markets", [])
            for market in markets:
                outcomes = market.get("outcomes", ["Yes", "No"])
                prices = market.get("outcomePrices", ["0.5", "0.5"])
                
                if len(prices) >= 2:
                    question = market.get("question", "").lower()
                    
                    if "draw" in question:
                        draw_odds = float(prices[0])
                    elif home_team.lower() in question:
                        home_odds = float(prices[0])
                    elif away_team.lower() in question:
                        away_odds = float(prices[0])
            
            # Normaliza odds
            total = home_odds + draw_odds + away_odds
            if total > 0:
                home_odds /= total
                draw_odds /= total
                away_odds /= total
            
            return Match(
                match_id=event.get("id", f"poly_{int(time.time())}"),
                home_team=home_team,
                away_team=away_team,
                start_time=start_time,
                league=league,
                condition_id=event.get("condition_id", ""),
                home_odds=round(home_odds, 3),
                draw_odds=round(draw_odds, 3),
                away_odds=round(away_odds, 3)
            )
            
        except Exception as e:
            log.debug(f"Erro ao parsear evento: {e}")
            return None
    
    def _extract_teams(self, title: str) -> Optional[Tuple[str, str]]:
        """Extrai times do título"""
        for sep in [" vs ", " VS ", " v ", " - ", " – ", " x "]:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    return parts[0].strip(), parts[1].strip()
        return None
    
    def _get_mock_matches(self) -> List[Match]:
        """Dados simulados para teste"""
        now = datetime.utcnow()
        matches = []
        
        mock_games = [
            ("Arsenal", "Chelsea", 0.42, 0.28, 0.30),
            ("Liverpool", "Man City", 0.38, 0.27, 0.35),
            ("Barcelona", "Real Madrid", 0.45, 0.25, 0.30),
            ("Bayern", "Dortmund", 0.48, 0.24, 0.28),
            ("Flamengo", "Palmeiras", 0.40, 0.28, 0.32),
        ]
        
        for i, (h, a, ho, do, ao) in enumerate(mock_games):
            match = Match(
                match_id=f"mock_{i}",
                home_team=h,
                away_team=a,
                start_time=now + timedelta(hours=2*(i+1)),
                league="Mock League",
                home_odds=ho,
                draw_odds=do,
                away_odds=ao
            )
            matches.append(match)
        
        return matches
    
    def get_live_score(self, match: Match) -> Tuple[int, int, int, str]:
        """Simula placar ao vivo"""
        elapsed = (datetime.utcnow() - match.start_time.replace(tzinfo=None)).total_seconds() / 60
        minute = max(0, min(95, int(elapsed)))
        
        if minute < 1:
            return 0, 0, 0, "not_started"
        elif minute >= 90:
            return 90, 2, 1, "finished"
        
        home_score = 1 if minute > 30 and match.home_odds > 0.4 else 0
        away_score = 1 if minute > 60 and match.away_odds > 0.4 else 0
        
        return minute, home_score, away_score, "live"

# ============= ESTRATÉGIA =============
class StrategyEngine:
    """Motor de estratégia"""
    
    def __init__(self, config: BotConfig):
        self.config = config
    
    def should_enter(self, match: Match, current_positions: int) -> Tuple[bool, str, float, float]:
        """Decide se deve entrar"""
        
        if current_positions >= self.config.max_open_positions:
            return False, "", 0, 0
        
        hours_until = match.time_until
        if not (self.config.min_hours_before_game <= hours_until <= self.config.max_hours_before_game):
            return False, "", 0, 0
        
        probs = match.normalized_probs
        best_outcome = None
        best_edge = 0
        
        for outcome in ["home", "draw", "away"]:
            market_price = getattr(match, f"{outcome}_odds", 0)
            model_prob = probs.get(outcome, 0.33)
            edge = model_prob - market_price
            
            if edge > self.config.min_edge_pct and edge < self.config.max_edge_pct:
                if edge > best_edge:
                    best_edge = edge
                    best_outcome = outcome
        
        if best_outcome:
            size = min(
                self.config.max_position_usdc,
                self.config.total_bankroll_usdc * self.config.bankroll_risk_pct
            )
            return True, best_outcome, best_edge, size
        
        return False, "", 0, 0
    
    def should_exit(self, position: Position, match: Match, current_price: float) -> List[Tuple[float, str]]:
        """Decide se deve sair"""
        exits = []
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        
        # Atualiza highest price
        if current_price > position.highest_price:
            position.highest_price = current_price
        
        # Profit targets
        for target in self.config.profit_targets:
            if pnl_pct >= target:
                exits.append((0.5, f"profit_{int(target*100)}%"))
                break
        
        # Stop loss
        for stop in self.config.stop_losses:
            if pnl_pct <= -stop:
                exits.append((1.0, f"stop_{int(stop*100)}%"))
                break
        
        # Trailing stop
        if pnl_pct > 0.15:
            stop_price = position.highest_price * (1 - self.config.trailing_stop_pct)
            if current_price < stop_price:
                exits.append((1.0, "trailing_stop"))
        
        # Eventos do jogo
        if match.status == "live":
            if match.minute >= 90:
                exits.append((1.0, "match_end"))
            elif ((position.outcome == "home" and match.home_score > match.away_score) or
                  (position.outcome == "away" and match.away_score > match.home_score)):
                if pnl_pct > 0:
                    exits.append((0.3, "goal_for"))
        
        return exits

# ============= GERENCIADOR DE PORTFOLIO =============
class PortfolioManager:
    """Gerencia posições e PnL"""
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.total_pnl: float = 0.0
        self.daily_pnl: float = 0.0
        self._load_state()
    
    def add_position(self, position: Position):
        self.positions[position.position_id] = position
        log.info(f"[OPEN] {position.match} | {position.outcome} | ${position.size_usdc:.2f}")
        self._save_state()
    
    def close_position(self, position_id: str, exit_price: float, reason: str):
        if position_id not in self.positions:
            return
        
        pos = self.positions.pop(position_id)
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.pnl_usdc = (exit_price - pos.entry_price) * pos.shares
        pos.sell_reason = reason
        
        self.total_pnl += pos.pnl_usdc
        self.daily_pnl += pos.pnl_usdc
        self.closed_positions.append(pos)
        
        result = "✅" if pos.pnl_usdc >= 0 else "❌"
        log.info(f"[CLOSE] {result} {pos.match} | PnL: ${pos.pnl_usdc:.2f} | {reason}")
        
        self._save_state()
    
    def get_open_positions(self) -> List[Position]:
        return list(self.positions.values())
    
    def get_stats(self) -> Dict:
        wins = [p for p in self.closed_positions if p.pnl_usdc > 0]
        return {
            "open": len(self.positions),
            "closed": len(self.closed_positions),
            "total_pnl": self.total_pnl,
            "daily_pnl": self.daily_pnl,
            "win_rate": len(wins)/len(self.closed_positions) if self.closed_positions else 0
        }
    
    def _save_state(self):
        try:
            with open("portfolio.json", "w") as f:
                json.dump({"total_pnl": self.total_pnl}, f)
        except:
            pass
    
    def _load_state(self):
        try:
            if os.path.exists("portfolio.json"):
                with open("portfolio.json") as f:
                    data = json.load(f)
                    self.total_pnl = data.get("total_pnl", 0)
        except:
            pass

# ============= BOT PRINCIPAL =============
class PolymarketFootballBot:
    """Bot principal"""
    
    def __init__(self):
        self.poly = PolymarketClient(CONFIG)
        self.football = FootballDataClient(CONFIG)
        self.strategy = StrategyEngine(CONFIG)
        self.portfolio = PortfolioManager()
        
        self.running = False
        self.last_scan = 0
        self.tracked_matches = {}
        
        log.info("="*60)
        log.info("  POLYMARKET FOOTBALL BOT v3.0")
        log.info("="*60)
        log.info(f"  Modo: {'SIMULAÇÃO' if CONFIG.simulation_mode else 'LIVE'}")
        log.info(f"  Bankroll: ${CONFIG.total_bankroll_usdc:.2f}")
        log.info(f"  Max posições: {CONFIG.max_open_positions}")
        log.info("="*60)
        
        # Notifica Telegram
        send_telegram(
            f"<b>🚀 BOT INICIADO</b>\n"
            f"Modo: {'SIMULAÇÃO' if CONFIG.simulation_mode else 'LIVE'}\n"
            f"Bankroll: ${CONFIG.total_bankroll_usdc:.2f}"
        )
    
    def scan_pregame(self):
        """Scan por oportunidades"""
        
        if len(self.portfolio.positions) >= CONFIG.max_open_positions:
            return
        
        log.info("\n🔍 ESCANEANDO JOGOS...")
        matches = self.football.get_upcoming_matches()
        
        for match in matches:
            if match.match_id in self.tracked_matches:
                continue
            
            should_enter, outcome, edge, size = self.strategy.should_enter(
                match, len(self.portfolio.positions)
            )
            
            if should_enter:
                token_id = f"token_{match.match_id}_{outcome}"
                
                # Simula compra
                result = self.poly.place_order(token_id, size, "buy")
                
                if result["success"]:
                    position = Position(
                        position_id=result["order_id"],
                        match=match,
                        outcome=outcome,
                        token_id=token_id,
                        entry_price=result["price"],
                        size_usdc=size,
                        shares=result["shares"],
                        entry_time=datetime.utcnow()
                    )
                    
                    self.portfolio.add_position(position)
                    self.tracked_matches[match.match_id] = match
                    
                    log.info(f"  🟢 COMPROU {match.home_team} vs {match.away_team}")
                    log.info(f"     {outcome.upper()} @ ${result['price']:.3f} | Edge: {edge*100:.1f}%")
                    
                    send_telegram(
                        f"<b>🟢 COMPRA</b>\n"
                        f"{match.home_team} vs {match.away_team}\n"
                        f"Outcome: {outcome.upper()}\n"
                        f"Valor: ${size:.2f} @ {result['price']:.3f}\n"
                        f"Edge: {edge*100:.1f}%"
                    )
    
    def monitor_live(self):
        """Monitora jogos ao vivo"""
        
        positions = self.portfolio.get_open_positions()
        if not positions:
            return
        
        log.info(f"\n📊 MONITORANDO {len(positions)} POSIÇÕES:")
        
        for position in positions:
            match = position.match
            
            # Atualiza placar
            minute, hs, as_, status = self.football.get_live_score(match)
            match.minute = minute
            match.home_score = hs
            match.away_score = as_
            match.status = status
            
            # Preço atual
            current_price = 0.5  # Mock price
            
            # Log do status
            pnl = (current_price - position.entry_price) / position.entry_price
            score = f"{hs}-{as_}" if status == "live" else status
            log.info(f"  {match.home_team} {score} {match.away_team} [{minute}'] | PnL: {pnl*100:+.1f}%")
            
            # Decide saída
            exits = self.strategy.should_exit(position, match, current_price)
            
            for pct, reason in exits:
                if pct > 0 and position.shares > 0:
                    sell_result = self.poly.place_order(
                        position.token_id,
                        position.shares * current_price * pct,
                        "sell"
                    )
                    
                    if sell_result["success"]:
                        position.shares *= (1 - pct)
                        log.info(f"     🔴 VENDEU {pct*100:.0f}% | {reason}")
                        
                        send_telegram(
                            f"<b>🔴 VENDA</b>\n"
                            f"{match.home_team} vs {match.away_team}\n"
                            f"Motivo: {reason}\n"
                            f"Parcela: {pct*100:.0f}%\n"
                            f"PnL: {pnl*100:+.1f}%"
                        )
            
            # Se vendeu tudo
            if position.shares <= 0.01:
                self.portfolio.close_position(
                    position.position_id,
                    current_price,
                    "closed"
                )
    
    def print_status(self):
        """Mostra status"""
        stats = self.portfolio.get_stats()
        
        log.info("\n" + "="*60)
        log.info("  STATUS DO BOT")
        log.info("="*60)
        log.info(f"  Posições abertas: {stats['open']}")
        log.info(f"  Posições fechadas: {stats['closed']}")
        log.info(f"  PnL Total: ${stats['total_pnl']:.2f}")
        log.info(f"  PnL Hoje: ${stats['daily_pnl']:.2f}")
        if stats['closed'] > 0:
            log.info(f"  Win Rate: {stats['win_rate']*100:.1f}%")
        log.info("="*60)
        
        # Telegram a cada 30 min
        if int(time.time()) % 1800 < 10:
            send_telegram(
                f"<b>📊 STATUS</b>\n"
                f"Posições: {stats['open']} abertas\n"
                f"PnL Hoje: ${stats['daily_pnl']:.2f}\n"
                f"Win Rate: {stats['win_rate']*100:.1f}%"
            )
    
    def run_cycle(self):
        """Ciclo principal"""
        try:
            # Scan a cada 30 minutos
            if time.time() - self.last_scan > 1800:
                self.scan_pregame()
                self.last_scan = time.time()
            
            # Monitor a cada 60 segundos
            self.monitor_live()
            
            # Status a cada 10 minutos
            if int(time.time()) % 600 < 5:
                self.print_status()
                
        except Exception as e:
            log.error(f"Erro no ciclo: {e}")
    
    def start(self):
        """Inicia o bot"""
        self.running = True
        log.info("\n🚀 BOT INICIADO!\n")
        
        schedule.every(30).seconds.do(self.run_cycle)
        
        # Primeira execução
        self.scan_pregame()
        self.print_status()
        
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(5)
            except KeyboardInterrupt:
                break
        
        self.stop()
    
    def stop(self):
        """Para o bot"""
        self.running = False
        log.info("\n🛑 BOT FINALIZADO")
        self.print_status()
        
        send_telegram(f"<b>🛑 BOT FINALIZADO</b>\nPnL Total: ${self.portfolio.total_pnl:.2f}")

# ============= MAIN =============
if __name__ == "__main__":
    print("\n" + "🚀"*30)
    print("  POLYMARKET FOOTBALL BOT v3.0")
    print("  Modo: SIMULAÇÃO")
    print("🚀"*30 + "\n")
    
    bot = PolymarketFootballBot()
    
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
    except Exception as e:
        log.error(f"Erro fatal: {e}")
        bot.stop()
