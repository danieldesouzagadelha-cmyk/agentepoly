"""
=================================================================
    POLYMARKET FOOTBALL BOT v3.0 - CÓDIGO COMPLETO OTIMIZADO
    Estratégias: Event-Driven + Arbitragem + Gestão Avançada
    SEM dependências externas complexas (numpy opcional)
=================================================================
"""

import os
import json
import time
import hmac
import hashlib
import logging
import schedule
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple, Dict, Any
from collections import deque
import threading
from dotenv import load_dotenv

# Tentativa de importar numpy (opcional)
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("[INFO] NumPy não instalado. Usando implementações puras em Python.")

# Tentativa de importar WebSocket (opcional para modo real)
try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    print("[INFO] WebSocket não instalado. Usando REST polling (mais lento).")

# Tentativa de importar cliente Polymarket (opcional)
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, Side
    from py_clob_client.constants import POLYGON
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("[INFO] py-clob-client não instalado. Modo simulação apenas.")

# Carrega variáveis de ambiente
load_dotenv()

# ============= CONFIGURAÇÕES =============
@dataclass
class BotConfig:
    """Configurações principais do bot"""
    
    # ===== GESTÃO DE RISCO =====
    max_position_usdc: float = 100.0
    max_open_positions: int = 5
    total_bankroll_usdc: float = 1000.0
    bankroll_risk_pct: float = 0.05  # 5% do bankroll por aposta
    daily_loss_limit: float = 200.0   # Para stop diário
    weekly_loss_limit: float = 500.0  # Para stop semanal
    
    # ===== FILTROS DE ENTRADA =====
    min_edge_pct: float = 0.02        # 2% mínimo de vantagem
    max_edge_pct: float = 0.30        # 30% máximo (evita odds absurdas)
    min_hours_before_game: float = 1.0
    max_hours_before_game: float = 48.0
    min_odds: float = 0.15            # Mínimo 15% de chance
    max_odds: float = 0.85            # Máximo 85% de chance
    
    # ===== ESTRATÉGIA DE SAÍDA =====
    profit_targets: List[float] = field(default_factory=lambda: [0.20, 0.40, 0.60])
    stop_losses: List[float] = field(default_factory=lambda: [0.15, 0.30])
    trailing_stop_pct: float = 0.15
    scale_out_pcts: List[float] = field(default_factory=lambda: [0.3, 0.3, 0.4])
    max_hold_minutes: int = 90         # Tempo máximo em jogo
    
    # ===== ARBITRAGEM =====
    enable_arbitrage: bool = True
    min_arb_spread: float = 0.02       # 2% mínimo
    arb_max_capital: float = 200.0     # Capital para arbitragem
    arb_min_volume: float = 1000.0     # Volume mínimo em USDC
    
    # ===== CONFIGURAÇÕES TÉCNICAS =====
    host: str = "https://clob.polymarket.com"
    chain_id: int = 137  # Polygon mainnet
    simulation_mode: bool = True       # Começar em simulação sempre!
    use_websocket: bool = WEBSOCKET_AVAILABLE
    
    # ===== APIS =====
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    sportradar_key: str = field(default_factory=lambda: os.getenv("SPORTRADAR_API_KEY", ""))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    
    # ===== WALLET =====
    private_key: str = field(default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", ""))
    wallet_address: str = field(default_factory=lambda: os.getenv("POLYMARKET_WALLET_ADDRESS", ""))

# Instância global de configuração
CONFIG = BotConfig()

# ============= UTILITÁRIOS =============
class MovingAverage:
    """Média móvel simples sem numpy"""
    def __init__(self, window: int = 10):
        self.window = window
        self.values = deque(maxlen=window)
    
    def add(self, value: float):
        self.values.append(value)
    
    def mean(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)
    
    def std(self) -> float:
        """Desvio padrão amostral"""
        if len(self.values) < 2:
            return 0.0
        mean = self.mean()
        variance = sum((x - mean) ** 2 for x in self.values) / (len(self.values) - 1)
        return variance ** 0.5

def safe_float_division(a: float, b: float, default: float = 0.0) -> float:
    """Divisão segura evitando divisão por zero"""
    if b == 0 or abs(b) < 1e-10:
        return default
    return a / b

def format_currency(value: float) -> str:
    """Formata valor em dólar"""
    return f"${value:,.2f}"

def format_percent(value: float) -> str:
    """Formata percentual"""
    return f"{value*100:.1f}%"

# ============= LOGGING E TELEGRAM =============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("PolyBot")

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
        log.debug(f"Erro Telegram: {e}")

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
    
    # Odds
    home_odds: float = 0.0
    draw_odds: float = 0.0
    away_odds: float = 0.0
    
    # Live data
    minute: int = 0
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"  # scheduled, live, finished
    
    def __post_init__(self):
        if isinstance(self.start_time, str):
            self.start_time = datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
    
    @property
    def total_odds(self) -> float:
        return self.home_odds + self.draw_odds + self.away_odds
    
    @property
    def normalized_probs(self) -> Dict[str, float]:
        """Probabilidades normalizadas (somam 1)"""
        total = self.total_odds
        if total <= 0:
            return {"home": 0.33, "draw": 0.34, "away": 0.33}
        return {
            "home": self.home_odds / total,
            "draw": self.draw_odds / total,
            "away": self.away_odds / total
        }
    
    @property
    def time_until(self) -> float:
        """Horas até o jogo começar"""
        now = datetime.utcnow()
        start = self.start_time.replace(tzinfo=None)
        return (start - now).total_seconds() / 3600
    
    @property
    def is_live(self) -> bool:
        return self.status == "live"
    
    @property
    def is_finished(self) -> bool:
        return self.status == "finished"
    
    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team} ({self.league})"

@dataclass
class Position:
    """Representa uma posição aberta"""
    position_id: str
    match: Match
    outcome: str  # home, draw, away
    token_id: str
    entry_price: float
    size_usdc: float
    shares: float
    entry_time: datetime
    status: str = "open"
    exit_price: float = 0.0
    pnl_usdc: float = 0.0
    pnl_percent: float = 0.0
    sell_reason: str = ""
    
    # Para trailing stop
    highest_price: float = 0.0
    
    def __post_init__(self):
        if isinstance(self.entry_time, str):
            self.entry_time = datetime.fromisoformat(self.entry_time)
        self.highest_price = self.entry_price
    
    @property
    def current_pnl_percent(self, current_price: float) -> float:
        """Calcula PnL percentual atual"""
        if self.entry_price == 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price
    
    @property
    def holding_minutes(self) -> float:
        """Minutos desde a entrada"""
        delta = datetime.utcnow() - self.entry_time
        return delta.total_seconds() / 60

# ============= CLIENTE POLYMARKET =============
class PolymarketClient:
    """Cliente para API da Polymarket"""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PolyBot/3.0"
        })
        
        # Modo simulação
        self.simulation_mode = config.simulation_mode
        
        # Cache
        self.price_cache = {}
        self.fee_cache = {}
        self.last_fee_update = {}
        
        # WebSocket (se disponível)
        self.ws = None
        self.ws_thread = None
        self.ws_running = False
        self.orderbooks = {}
        
        # Cliente oficial (se disponível)
        self.clob_client = None
        if not self.simulation_mode and CLOB_AVAILABLE:
            self._init_clob_client()
        
        log.info(f"[CLIENT] Inicializado. Modo: {'SIMULAÇÃO' if self.simulation_mode else 'REAL'}")
    
    def _init_clob_client(self):
        """Inicializa cliente CLOB oficial"""
        try:
            self.clob_client = ClobClient(
                host=self.config.host,
                chain_id=self.config.chain_id,
                key=self.config.private_key,
                signature_type=2,
                funder=self.config.wallet_address
            )
            creds = self.clob_client.create_or_derive_api_creds()
            self.clob_client.set_api_creds(creds)
            log.info("[OK] Cliente CLOB inicializado")
        except Exception as e:
            log.error(f"Erro ao inicializar CLOB: {e}")
            self.simulation_mode = True
    
    def _get_fee_rate(self, token_id: str, side: str) -> int:
        """Obtém taxa atual (crítico pós-fev/2026)"""
        if self.simulation_mode:
            return 0
        
        cache_key = f"{token_id}_{side}"
        
        # Cache por 5 segundos
        if cache_key in self.fee_cache:
            age = time.time() - self.last_fee_update.get(cache_key, 0)
            if age < 5:
                return self.fee_cache[cache_key]
        
        try:
            url = f"{self.config.host}/fee-rate"
            resp = self.session.get(url, params={
                "token_id": token_id,
                "side": side
            }, timeout=3).json()
            
            fee = int(resp.get("fee_rate_bps", 0))
            self.fee_cache[cache_key] = fee
            self.last_fee_update[cache_key] = time.time()
            return fee
        except Exception as e:
            log.debug(f"Erro ao consultar taxa: {e}")
            return 0
    
    def get_order_book(self, token_id: str) -> Dict[str, Any]:
        """Obtém book de ordens"""
        # Tenta cache do WebSocket primeiro
        if token_id in self.orderbooks:
            book = self.orderbooks[token_id]
            age = time.time() - book.get("timestamp", 0)
            if age < 2:  # Cache válido por 2s
                return book
        
        # Fallback para REST
        try:
            url = f"{self.config.host}/book"
            resp = self.session.get(url, params={"token_id": token_id}, timeout=3).json()
            
            book = {
                "bids": [(float(b["price"]), float(b["size"])) for b in resp.get("bids", [])],
                "asks": [(float(a["price"]), float(a["size"])) for a in resp.get("asks", [])],
                "timestamp": time.time()
            }
            
            # Atualiza cache
            self.orderbooks[token_id] = book
            return book
        except Exception as e:
            log.debug(f"Erro ao obter book: {e}")
            return {"bids": [], "asks": [], "timestamp": time.time()}
    
    def get_mid_price(self, token_id: str) -> float:
        """Obtém preço médio (bid+ask)/2"""
        book = self.get_order_book(token_id)
        
        best_bid = book["bids"][0][0] if book["bids"] else 0.0
        best_ask = book["asks"][0][0] if book["asks"] else 1.0
        
        if best_bid == 0 and best_ask == 1.0:
            return 0.5
        if best_bid == 0:
            return best_ask * 0.95
        if best_ask == 1.0:
            return best_bid * 1.05
        
        return (best_bid + best_ask) / 2
    
    def get_best_prices(self, token_id: str) -> Tuple[float, float]:
        """Retorna melhor bid e ask"""
        book = self.get_order_book(token_id)
        
        best_bid = book["bids"][0][0] if book["bids"] else 0.0
        best_ask = book["asks"][0][0] if book["asks"] else 1.0
        
        return best_bid, best_ask
    
    def place_order(self, token_id: str, size_usdc: float, side: str, 
                   order_type: str = "market") -> Dict[str, Any]:
        """
        Coloca uma ordem na Polymarket
        side: "buy" ou "sell"
        order_type: "market" (taker) ou "limit" (maker)
        """
        if self.simulation_mode:
            bid, ask = self.get_best_prices(token_id)
            price = ask if side == "buy" else bid
            shares = size_usdc / price
            
            log.info(f"[SIM] {side.upper()} {size_usdc:.2f} USDC @ {price:.4f} "
                    f"({order_type}) | Shares: {shares:.2f}")
            
            return {
                "success": True,
                "order_id": f"SIM-{int(time.time())}",
                "price": price,
                "shares": shares,
                "simulated": True
            }
        
        if not self.clob_client:
            log.error("Cliente CLOB não disponível")
            return {"success": False, "error": "CLOB not available"}
        
        try:
            # 1. Consulta taxa atual
            fee_rate = self._get_fee_rate(token_id, side)
            
            # 2. Obtém melhor preço
            bid, ask = self.get_best_prices(token_id)
            
            if side == "buy":
                if order_type == "market":
                    price = ask  # Compra no ask (taker)
                else:
                    price = bid * 0.998  # Abaixo do bid (maker)
            else:  # sell
                if order_type == "market":
                    price = bid  # Vende no bid (taker)
                else:
                    price = ask * 1.002  # Acima do ask (maker)
            
            shares = size_usdc / price
            
            # 3. Cria ordem com fee incluso
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=Side.BUY if side == "buy" else Side.SELL,
                token_id=token_id,
                fee_rate_bps=fee_rate
            )
            
            resp = self.clob_client.create_and_post_order(order_args)
            
            log.info(f"[ORDER] {side.upper()} {size_usdc:.2f} USDC @ {price:.4f} | "
                    f"Fee: {fee_rate}bps")
            
            return {
                "success": True,
                "order_id": resp.get("orderID"),
                "price": price,
                "shares": shares
            }
            
        except Exception as e:
            log.error(f"Erro na ordem: {e}")
            return {"success": False, "error": str(e)}
    
    def get_balance(self) -> float:
        """Obtém saldo em USDC"""
        if self.simulation_mode:
            return self.config.total_bankroll_usdc
        
        try:
            if self.clob_client:
                return float(self.clob_client.get_balance())
        except Exception as e:
            log.debug(f"Erro ao obter saldo: {e}")
        
        return 0.0

# ============= CLIENTE DE DADOS DE FUTEBOL =============
# ============= CLIENTE DE DADOS DE FUTEBOL - VERSÃO REAL =============
class FootballDataClient:
    """Cliente para dados de futebol usando API real da Polymarket"""
    
    # Tags de futebol confirmadas que funcionam no Polymarket [citation:2]
    SOCCER_TAGS = {
        # TOP 5 Europeias
        "premier-league": "Premier League",
        "laliga": "La Liga",
        "bundesliga": "Bundesliga",
        "serie-a": "Serie A",
        "ligue-1": "Ligue 1",
        
        # Outras Europeias
        "champions-league": "Champions League",
        "europa-league": "Europa League",
        "eredivisie": "Eredivisie",
        "primeira-liga": "Primeira Liga",
        "scottish-premiership": "Scottish Premiership",
        
        # Sul-Americanas ✅ CONFIRMADAS
        "brazil-serie-a": "Brasileirão Série A",
        "argentina-primera": "Argentine Primera",
        "liga-mx": "Liga MX",
        "copa-libertadores": "Copa Libertadores",
        "copa-sudamericana": "Copa Sudamericana",
        
        # Copas
        "fa-cup": "FA Cup",
        "copa-del-rey": "Copa del Rey",
        "dfb-pokal": "DFB-Pokal",
        "coppa-italia": "Coppa Italia",
        "taca-de-portugal": "Taça de Portugal"
    }
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.cache = {}
        self.last_request = 0
        self.rate_limit = 1.0  # 1 segundo entre requests
        
        log.info(f"[INIT] FootballDataClient inicializado")
        log.info(f"[TAGS] Monitorando {len(self.SOCCER_TAGS)} ligas")
    
    def _rate_limit(self):
        """Respeita rate limit da API"""
        elapsed = time.time() - self.last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request = time.time()
    
    def get_upcoming_matches(self) -> List[Match]:
        """Busca jogos de futebol ao vivo da Polymarket"""
        
        all_matches = []
        
        for tag_slug, league_name in self.SOCCER_TAGS.items():
            try:
                log.info(f"[FETCH] Buscando {league_name}...")
                
                # 1. Primeiro busca eventos pela tag (método que funciona) [citation:2]
                events = self._fetch_events_by_tag(tag_slug)
                
                if not events:
                    log.debug(f"[SKIP] Nenhum evento para {league_name}")
                    continue
                
                # 2. Para cada evento, busca mercados
                for event in events[:5]:  # Limite por evento
                    match = self._parse_event_to_match(event, league_name)
                    if match:
                        # 3. Enriquecer com dados de preço do CLOB
                        self._enrich_with_prices(match)
                        all_matches.append(match)
                        
                        log.info(f"  ✅ {match.home_team} vs {match.away_team} | "
                                f"Odds: {match.home_odds:.2f}/{match.draw_odds:.2f}/{match.away_odds:.2f}")
                
                # Pausa entre requisições
                time.sleep(0.5)
                
            except Exception as e:
                log.error(f"[ERROR] Falha ao buscar {league_name}: {e}")
                continue
        
        log.info(f"[RESULT] Total de {len(all_matches)} jogos encontrados")
        
        # Se não encontrou nada, usa dados mockados como fallback
        if not all_matches:
            log.warning("[FALLBACK] Nenhum jogo encontrado. Usando dados simulados.")
            return self._get_mock_matches()
        
        return all_matches
    
    def _fetch_events_by_tag(self, tag_slug: str) -> List[Dict]:
        """Busca eventos por tag usando Gamma API"""
        self._rate_limit()
        
        try:
            url = f"{self.gamma_url}/events"
            params = {
                "tag_slug": tag_slug,
                "active": "true",        # Só eventos ativos
                "closed": "false",        # Não fechados
                "limit": 20,              # Máximo por requisição
                "order": "start_date",
                "ascending": "true"
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                log.debug(f"HTTP {response.status_code} para {tag_slug}")
                return []
            
            events = response.json()
            return events if isinstance(events, list) else []
            
        except Exception as e:
            log.debug(f"Erro ao buscar {tag_slug}: {e}")
            return []
    
    def _parse_event_to_match(self, event: Dict, league: str) -> Optional[Match]:
        """Converte evento da Polymarket em objeto Match"""
        try:
            # Título do evento (ex: "Arsenal vs Chelsea")
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
            
            # Markets do evento
            markets = event.get("markets", [])
            
            # Inicializa odds
            home_odds = 0.5
            draw_odds = 0.0
            away_odds = 0.5
            
            # Mapeia mercados (Yes/No)
            for market in markets:
                outcomes = market.get("outcomes", [])
                outcome_prices = market.get("outcomePrices", [])
                
                if not outcomes or not outcome_prices:
                    continue
                
                # Tenta identificar o tipo de mercado pelo título
                market_title = market.get("question", "").lower()
                
                if "win" in market_title or "winner" in market_title:
                    # É um mercado de vencedor
                    if len(outcomes) == 2:
                        # Pode ser "Yes/No" para "Team A wins"
                        if home_team.lower() in market_title:
                            home_odds = float(outcome_prices[0])
                        elif away_team.lower() in market_title:
                            away_odds = float(outcome_prices[0])
                
                elif "draw" in market_title or "empate" in market_title:
                    # Mercado de empate
                    draw_odds = float(outcome_prices[0]) if outcome_prices else 0.3
            
            # Se não encontrou draw, assume 0.28 (média)
            if draw_odds == 0:
                draw_odds = 0.28
            
            # Normaliza odds
            total = home_odds + draw_odds + away_odds
            if total > 0:
                home_odds /= total
                draw_odds /= total
                away_odds /= total
            
            # Cria o match
            match = Match(
                match_id=event.get("id", f"poly_{int(time.time())}"),
                home_team=home_team,
                away_team=away_team,
                start_time=start_time,
                league=league,
                condition_id=event.get("condition_id", ""),
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                token_ids={}
            )
            
            # Adiciona token IDs se disponíveis
            for market in markets:
                clob_token_ids = market.get("clobTokenIds", [])
                if clob_token_ids and len(clob_token_ids) >= 1:
                    # Tenta mapear token_id para o resultado
                    market_title = market.get("question", "").lower()
                    if home_team.lower() in market_title:
                        match.token_ids["home"] = clob_token_ids[0]
                    elif away_team.lower() in market_title:
                        match.token_ids["away"] = clob_token_ids[0]
                    elif "draw" in market_title:
                        match.token_ids["draw"] = clob_token_ids[0]
            
            return match
            
        except Exception as e:
            log.debug(f"Erro ao parsear evento: {e}")
            return None
    
    def _extract_teams(self, title: str) -> Optional[Tuple[str, str]]:
        """Extrai times do título do evento"""
        # Exemplos: "Arsenal vs Chelsea", "Barcelona - Real Madrid"
        for separator in [" vs ", " VS ", " v ", " - ", " – ", " x "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) >= 2:
                    return parts[0].strip(), parts[1].strip()
        
        # Fallback: split por espaços
        words = title.split()
        if len(words) >= 3:
            # Assume formato "Team A Team B" (menos comum)
            mid = len(words) // 2
            return " ".join(words[:mid]), " ".join(words[mid:])
        
        return None
    
    def _enrich_with_prices(self, match: Match):
        """Busca preços atualizados do CLOB"""
        try:
            # Para cada token_id, busca preço
            for outcome, token_id in match.token_ids.items():
                if token_id:
                    # Busca book de ordens
                    url = f"{self.clob_url}/book"
                    params = {"token_id": token_id}
                    
                    response = requests.get(url, params=params, timeout=5)
                    if response.status_code == 200:
                        book = response.json()
                        bids = book.get("bids", [])
                        asks = book.get("asks", [])
                        
                        if bids and asks:
                            best_bid = float(bids[0].get("price", 0))
                            best_ask = float(asks[0].get("price", 0))
                            
                            # Preço médio
                            price = (best_bid + best_ask) / 2
                            
                            # Atualiza a odd correspondente
                            if outcome == "home":
                                match.home_odds = price
                            elif outcome == "away":
                                match.away_odds = price
                            elif outcome == "draw":
                                match.draw_odds = price
        except Exception as e:
            log.debug(f"Erro ao enriquecer preços: {e}")
    
    def get_live_score(self, match: Match) -> Tuple[int, int, int, str]:
        """Busca placar ao vivo"""
        
        # Tenta API da Sportradar se tiver key
        if self.config.sportradar_key:
            try:
                # Exemplo: usar match_id como referência
                url = f"https://api.sportradar.com/soccer/trial/v4/en/matches/{match.match_id}/timeline.json"
                response = requests.get(
                    url, 
                    params={"api_key": self.config.sportradar_key},
                    timeout=5
                )
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("sport_event_status", {})
                    minute = status.get("match_time", 0)
                    home = status.get("home_score", 0)
                    away = status.get("away_score", 0)
                    status_str = status.get("status", "live")
                    
                    return minute, home, away, status_str
                    
            except Exception as e:
                log.debug(f"Erro Sportradar: {e}")
        
        # Fallback: simula baseado no tempo
        return self._mock_live_score(match)
    
    def _get_mock_matches(self) -> List[Match]:
        """Fallback: jogos simulados para quando API não retorna nada"""
        now = datetime.utcnow()
        matches = []
        
        # Jogos de hoje
        mock_games = [
            ("Arsenal", "Chelsea", 0.42, 0.28, 0.30),
            ("Liverpool", "Man City", 0.38, 0.27, 0.35),
            ("Barcelona", "Real Madrid", 0.45, 0.25, 0.30),
            ("Bayern", "Dortmund", 0.48, 0.24, 0.28),
            ("Flamengo", "Palmeiras", 0.40, 0.28, 0.32),
        ]
        
        for i, (home, away, h_odds, d_odds, a_odds) in enumerate(mock_games):
            match = Match(
                match_id=f"mock_{i}_{int(time.time())}",
                home_team=home,
                away_team=away,
                start_time=now + timedelta(hours=2*(i+1)),
                league="Mock League",
                home_odds=h_odds,
                draw_odds=d_odds,
                away_odds=a_odds
            )
            matches.append(match)
        
        log.info(f"[MOCK] Gerados {len(matches)} jogos simulados")
        return matches
    
    def _mock_live_score(self, match: Match) -> Tuple[int, int, int, str]:
        """Simula placar ao vivo"""
        elapsed = (datetime.utcnow() - match.start_time.replace(tzinfo=None)).total_seconds() / 60
        minute = max(0, min(95, int(elapsed)))
        
        if minute < 1:
            return 0, 0, 0, "not_started"
        elif minute >= 90:
            return 90, 2, 1, "finished"
        
        # Simula alguns gols baseado nas odds
        home_score = 1 if minute > 30 and match.home_odds > 0.4 else 0
        away_score = 1 if minute > 60 and match.away_odds > 0.4 else 0
        
        return minute, home_score, away_score, "live"

# ============= ESTRATÉGIA DE ARBITRAGEM =============
class ArbitrageEngine:
    """Detecta oportunidades de arbitragem"""
    
    def __init__(self, client: PolymarketClient, config: BotConfig):
        self.client = client
        self.config = config
        self.opportunities_found = 0
        self.arb_pnl = 0.0
    
    def scan_markets(self, matches: List[Match]) -> List[Dict]:
        """Escaneia mercados por oportunidades de arbitragem"""
        opportunities = []
        
        for match in matches:
            # Pula jogos sem odds
            if match.total_odds <= 0:
                continue
            
            # Arbitragem 1: YES + NO < 1
            # Precisa dos token_ids reais aqui
            # Este é um exemplo conceitual
            
            # Exemplo: Se home_odds + (1-home_odds) < 0.98
            if match.home_odds > 0 and match.home_odds < 0.5:
                # Simula oportunidade de arbitragem
                total = match.home_odds + (1 - match.home_odds)
                if total < 0.98:  # 2% de desconto
                    size = min(
                        self.config.arb_max_capital,
                        self.config.total_bankroll_usdc * 0.1
                    )
                    
                    opp = {
                        "type": "yes_no_arb",
                        "match": match,
                        "outcome": "home",
                        "buy_price": match.home_odds,
                        "sell_price": 1 - match.home_odds,
                        "spread": 1 - total,
                        "size": size,
                        "expected_profit": size * (1 - total)
                    }
                    opportunities.append(opp)
        
        return opportunities
    
    def execute_arbitrage(self, opportunity: Dict) -> bool:
        """Executa uma oportunidade de arbitragem"""
        
        log.info(f"[ARB] Oportunidade: {opportunity['match']} | "
                f"Spread: {opportunity['spread']*100:.2f}% | "
                f"Lucro esperado: ${opportunity['expected_profit']:.2f}")
        
        # Em simulação, registra como sucesso
        if self.client.simulation_mode:
            self.opportunities_found += 1
            self.arb_pnl += opportunity['expected_profit']
            log.info(f"[ARB] Executada em simulação")
            return True
        
        # Implementação real exigiria token_ids corretos
        # e execução em duas pernas
        log.warning("[ARB] Execução real não implementada sem token_ids")
        return False

# ============= ESTRATÉGIA PRINCIPAL =============
class StrategyEngine:
    """Motor de estratégia principal"""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.price_history = {}  # match_id -> {outcome: deque}
        self.volume_history = {}  # match_id -> deque
    
    def _get_price_history(self, match: Match, outcome: str) -> MovingAverage:
        """Obtém histórico de preços para um mercado"""
        key = f"{match.match_id}_{outcome}"
        if key not in self.price_history:
            self.price_history[key] = MovingAverage(window=10)
        return self.price_history[key]
    
    def calculate_edge(self, match: Match, outcome: str) -> Tuple[float, float]:
        """
        Calcula edge (vantagem) para um resultado
        Retorna: (edge_percent, confidence_score)
        """
        probs = match.normalized_probs
        market_price = getattr(match, f"{outcome}_odds", 0)
        
        if market_price <= 0:
            return 0.0, 0.0
        
        # Edge básico: diferença entre modelo e mercado
        model_prob = probs.get(outcome, 0.33)
        basic_edge = model_prob - market_price
        
        # Fator de momentum (se preço está subindo)
        history = self._get_price_history(match, outcome)
        if len(history.values) >= 3:
            recent = list(history.values)[-3:]
            momentum = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
        else:
            momentum = 0
        
        # Fator de confiança baseado em liquidez
        # Quanto maior o volume, maior a confiança
        confidence = 0.5 + (momentum * 2)  # Simples por enquanto
        
        # Edge ajustado
        edge = basic_edge * (1 + momentum)
        
        return edge, min(1.0, max(0.0, confidence))
    
    def should_enter(self, match: Match, current_positions: int) -> Tuple[bool, str, float, float]:
        """Decide se deve entrar em uma posição"""
        
        # Verifica limite de posições
        if current_positions >= self.config.max_open_positions:
            return False, "", 0.0, 0.0
        
        # Verifica tempo até o jogo
        hours_until = match.time_until
        if not (self.config.min_hours_before_game <= hours_until <= self.config.max_hours_before_game):
            return False, "", 0.0, 0.0
        
        # Verifica odds mínimas/máximas
        if match.home_odds < self.config.min_odds or match.home_odds > self.config.max_odds:
            if match.draw_odds < self.config.min_odds or match.draw_odds > self.config.max_odds:
                if match.away_odds < self.config.min_odds or match.away_odds > self.config.max_odds:
                    return False, "", 0.0, 0.0
        
        best_outcome = None
        best_edge = 0
        best_confidence = 0
        
        # Avalia cada resultado
        for outcome in ["home", "draw", "away"]:
            edge, confidence = self.calculate_edge(match, outcome)
            
            if edge > self.config.min_edge_pct and edge < self.config.max_edge_pct:
                if edge > best_edge and confidence > 0.4:
                    best_edge = edge
                    best_confidence = confidence
                    best_outcome = outcome
        
        if best_outcome and best_edge > 0:
            # Calcula tamanho da posição baseado na confiança
            size_multiplier = 0.5 + (best_confidence * 0.5)  # 0.5 a 1.0
            position_size = min(
                self.config.max_position_usdc,
                self.config.total_bankroll_usdc * self.config.bankroll_risk_pct * size_multiplier
            )
            
            log.info(f"[EDGE] {match} | {best_outcome} | "
                    f"Edge: {best_edge*100:.2f}% | Confiança: {best_confidence*100:.1f}% | "
                    f"Size: ${position_size:.2f}")
            
            return True, best_outcome, best_edge, position_size
        
        return False, "", 0.0, 0.0
    
    def should_exit(self, position: Position, match: Match, current_price: float) -> List[Tuple[float, str]]:
        """
        Decide se deve sair de uma posição
        Retorna lista de (percentual_a_sair, motivo)
        """
        exits = []
        
        # Atualiza highest price para trailing stop
        if current_price > position.highest_price:
            position.highest_price = current_price
        
        # Calcula PnL percentual
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        
        # 1. Profit taking em múltiplos níveis
        for target in self.config.profit_targets:
            if pnl_pct >= target and position.shares > 0.01:
                # Sai 30% em cada target
                exit_pct = 0.3
                exits.append((exit_pct, f"take_profit_{int(target*100)}%"))
                # Nota: não reduzimos shares aqui porque isso é apenas decisão
        
        # 2. Stop loss
        for stop in self.config.stop_losses:
            if pnl_pct <= -stop and position.shares > 0.01:
                exit_pct = 1.0 if stop == max(self.config.stop_losses) else 0.5
                exits.append((exit_pct, f"stop_loss_{int(stop*100)}%"))
        
        # 3. Trailing stop (ativa após 15% de lucro)
        if pnl_pct > 0.15:
            trailing_stop_price = position.highest_price * (1 - self.config.trailing_stop_pct)
            if current_price < trailing_stop_price:
                exits.append((1.0, "trailing_stop"))
        
        # 4. Eventos de jogo
        if match.is_live:
            # Gol a favor
            if ((position.outcome == "home" and match.home_score > match.away_score) or
                (position.outcome == "away" and match.away_score > match.home_score)):
                if pnl_pct > 0.1:
                    exits.append((0.5, "favorable_goal"))
            
            # Gol contra
            if ((position.outcome == "home" and match.away_score > match.home_score) or
                (position.outcome == "away" and match.home_score > match.away_score)):
                exits.append((1.0, "adverse_goal"))
        
        # 5. Tempo máximo
        if position.holding_minutes > self.config.max_hold_minutes:
            exits.append((1.0, "max_time"))
        
        # 6. Fim de jogo
        if match.is_finished:
            exits.append((1.0, "match_finished"))
        
        return exits

# ============= GERENCIADOR DE PORTFOLIO =============
# ============= GERENCIADOR DE PORTFOLIO =============
class PortfolioManager:
    """Gerencia posições e PnL"""
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.total_pnl: float = 0.0
        self.daily_pnl: float = 0.0
        self.weekly_pnl: float = 0.0
        self.last_reset = datetime.utcnow().date()
        
        self._load_state()
    
    def add_position(self, position: Position):
        """Adiciona nova posição"""
        self.positions[position.position_id] = position
        log.info(f"[OPEN] {position.match} | {position.outcome} | ${position.size_usdc:.2f}")
        self._save_state()
    
    def close_position(self, position_id: str, exit_price: float, reason: str):
        """Fecha uma posição"""
        if position_id not in self.positions:
            return
        
        pos = self.positions.pop(position_id)
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.pnl_usdc = (exit_price - pos.entry_price) * pos.shares
        pos.pnl_percent = (exit_price - pos.entry_price) / pos.entry_price
        pos.sell_reason = reason
        
        # Atualiza PnL
        self.total_pnl += pos.pnl_usdc
        self.daily_pnl += pos.pnl_usdc
        self.weekly_pnl += pos.pnl_usdc
        self.closed_positions.append(pos)
        
        # Log
        result = "✅ LUCRO" if pos.pnl_usdc >= 0 else "❌ PERDA"
        log.info(f"[CLOSE] {result} | {pos.match} | {pos.outcome} | "
                f"PnL: ${pos.pnl_usdc:.2f} ({pos.pnl_percent*100:.1f}%) | {reason}")
        
        self._save_state()
    
    def get_open_positions(self) -> List[Position]:
        """Retorna posições abertas"""
        return list(self.positions.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do portfolio"""
        wins = [p for p in self.closed_positions if p.pnl_usdc > 0]
        losses = [p for p in self.closed_positions if p.pnl_usdc <= 0]
        
        total_closed = len(self.closed_positions)
        win_rate = len(wins) / total_closed if total_closed > 0 else 0
        
        # Média de lucro/perda
        avg_win = sum(p.pnl_usdc for p in wins) / len(wins) if wins else 0
        avg_loss = sum(p.pnl_usdc for p in losses) / len(losses) if losses else 0
        
        return {
            "open_positions": len(self.positions),
            "closed_positions": total_closed,
            "total_pnl": self.total_pnl,
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "win_rate": win_rate,
            "wins": len(wins),
            "losses": len(losses),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": abs(avg_win / avg_loss) if avg_loss != 0 else 0
        }
    
    def reset_daily(self):
        """Reset contador diário"""
        self.daily_pnl = 0.0
        self.last_reset = datetime.utcnow().date()
        log.info("[RESET] Daily PnL reset")
    
    def check_limits(self) -> Tuple[bool, str]:
        """Verifica se limites foram atingidos"""
        # Limite diário
        if abs(self.daily_pnl) >= CONFIG.daily_loss_limit:
            return True, f"Daily loss limit reached: ${self.daily_pnl:.2f}"
        
        # Limite semanal
        if abs(self.weekly_pnl) >= CONFIG.weekly_loss_limit:
            return True, f"Weekly loss limit reached: ${self.weekly_pnl:.2f}"
        
        return False, ""
    
    def _save_state(self):
        """Salva estado em arquivo"""
        try:
            state = {
                "positions": {
                    k: {
                        "position_id": v.position_id,
                        "match_id": v.match.match_id,
                        "outcome": v.outcome,
                        "token_id": v.token_id,
                        "entry_price": v.entry_price,
                        "size_usdc": v.size_usdc,
                        "shares": v.shares,
                        "entry_time": v.entry_time.isoformat(),
                        "status": v.status,
                        "highest_price": v.highest_price
                    }
                    for k, v in self.positions.items()
                },
                "total_pnl": self.total_pnl,
                "daily_pnl": self.daily_pnl,
                "weekly_pnl": self.weekly_pnl,
                "last_reset": self.last_reset.isoformat()
            }
            
            with open("portfolio_state.json", "w") as f:
                json.dump(state, f, indent=2)
                
        except Exception as e:
            log.debug(f"Erro ao salvar estado: {e}")
    
    def _load_state(self):
        """Carrega estado do arquivo"""
        try:
            if not os.path.exists("portfolio_state.json"):
                return
            
            with open("portfolio_state.json", "r") as f:
                state = json.load(f)
            
            self.total_pnl = state.get("total_pnl", 0.0)
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.weekly_pnl = state.get("weekly_pnl", 0.0)
            
            last_reset = state.get("last_reset")
            if last_reset:
                self.last_reset = datetime.fromisoformat(last_reset).date()
            
            # Se mudou de dia, reseta daily
            if self.last_reset != datetime.utcnow().date():
                self.reset_daily()
            
            log.info(f"[LOAD] Portfolio carregado | PnL Total: ${self.total_pnl:.2f}")
            
        except Exception as e:
            log.debug(f"Erro ao carregar estado: {e}")
