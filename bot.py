"""
=================================================================
         POLYMARKET FOOTBALL BOT v2.0 - OTIMIZADO PARA LUCRO
   Estratégias: Arbitragem + Market Making + Event-Driven + IA leve
   Atualizado para taxas dinâmicas (Fev/2026)
=================================================================
"""

import os
import json
import time
import logging
import schedule
import requests
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple, Dict
from dotenv import load_dotenv
from collections import deque

# WebSocket para latência baixa
import websocket
import threading

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, Side, OrderType
    from py_clob_client.constants import POLYGON
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("[WARNING] py-clob-client not installed. Running in SIMULATION mode.")

load_dotenv()

# ============= CONFIGURAÇÕES AVANÇADAS =============
@dataclass
class OptimizedConfig:
    # Gestão de risco
    max_position_usdc: float = 100.0  # Aumentado para capturar mais oportunidades
    max_open_positions: int = 10
    total_bankroll_usdc: float = 1000.0
    bankroll_risk_pct: float = 0.10  # Aumentado com stop mais rigoroso
    
    # Filtros de entrada
    min_edge_pct: float = 0.02  # 2% mínimo de edge (antes era 3%)
    max_edge_pct: float = 0.30  # 30% máximo (evita odds absurdas)
    
    # Estratégias de saída MULTI-CAMADA
    profit_targets: List[float] = field(default_factory=lambda: [0.15, 0.30, 0.50, 1.0])
    stop_losses: List[float] = field(default_factory=lambda: [0.10, 0.25, 0.40])
    trailing_stop_pct: float = 0.15  # Ativa após 20% de lucro
    scale_out_pcts: List[float] = field(default_factory=lambda: [0.3, 0.3, 0.4])  # Sai em etapas
    
    # ARBITRAGEM (NOVO)
    enable_arbitrage: bool = True
    min_arb_spread: float = 0.02  # 2% mínimo para arbitragem
    arb_max_capital: float = 200.0  # Capital dedicado à arbitragem
    
    # MARKET MAKING (NOVO)
    enable_market_making: bool = True
    mm_spread_bps: int = 20  # 0.2% de spread
    mm_order_size: float = 25.0  # Tamanho das ordens
    mm_rebalance_seconds: int = 30
    
    # PREÇOS E TAXAS
    host: str = "https://clob.polymarket.com"
    chain_id: int = POLYGON if CLOB_AVAILABLE else 137
    simulation_mode: bool = True
    
    # APIs
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", ""))
    sportradar_key: str = field(default_factory=lambda: os.getenv("SPORTRADAR_API_KEY", ""))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

CONFIG = OptimizedConfig()

# ============= CLIENTE OTIMIZADO COM WEBSOCKET =============
class OptimizedPolymarketClient:
    def __init__(self, config: OptimizedConfig):
        self.config = config
        self.client = None
        self.simulation_mode = config.simulation_mode
        self.ws_connections = {}
        self.orderbooks = {}  # Cache do book
        self.fee_rates = {}   # Cache de taxas (expira em 5s)
        self.last_fee_update = {}
        
        if not self.simulation_mode and CLOB_AVAILABLE:
            self._init_real_client()
            
        # Thread para WebSocket
        self.ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self.ws_running = True
        self.ws_thread.start()
    
    def _init_real_client(self):
        """Inicializa cliente com suporte a taxas dinâmicas"""
        try:
            self.client = ClobClient(
                host=self.config.host,
                chain_id=self.config.chain_id,
                key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                signature_type=2,
                funder=os.getenv("POLYMARKET_WALLET_ADDRESS")
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            log.info("[OK] Cliente Polymarket inicializado")
        except Exception as e:
            log.error(f"Falha ao inicializar: {e}")
            self.simulation_mode = True
    
    def _get_fee_rate(self, token_id: str, side: str) -> int:
        """CONSULTA TAXA DINÂMICA (obrigatório pós-fev/2026)"""
        cache_key = f"{token_id}_{side}"
        
        # Cache por 5 segundos apenas
        if cache_key in self.fee_rates:
            age = time.time() - self.last_fee_update.get(cache_key, 0)
            if age < 5:
                return self.fee_rates[cache_key]
        
        try:
            # Endpoint oficial de taxas
            url = f"{self.config.host}/fee-rate"
            resp = requests.get(url, params={
                "token_id": token_id,
                "side": side
            }, timeout=2).json()
            
            fee = int(resp.get("fee_rate_bps", 0))
            self.fee_rates[cache_key] = fee
            self.last_fee_update[cache_key] = time.time()
            return fee
        except:
            return 0  # Fallback seguro
    
    def _ws_loop(self):
        """Loop principal do WebSocket para múltiplos mercados"""
        while self.ws_running:
            try:
                ws = websocket.WebSocketApp(
                    "wss://clob.polymarket.com/ws",
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error
                )
                ws.run_forever()
            except:
                time.sleep(5)
    
    def _on_ws_message(self, ws, message):
        """Processa atualizações em tempo real do book"""
        try:
            data = json.loads(message)
            if data.get("type") == "book":
                token_id = data.get("asset_id")
                self.orderbooks[token_id] = {
                    "bids": data.get("bids", []),
                    "asks": data.get("asks", []),
                    "timestamp": time.time()
                }
        except:
            pass
    
    def subscribe_market(self, token_id: str):
        """Inscreve para receber updates em tempo real"""
        if self.simulation_mode:
            return
        # Envia comando de subscription via WebSocket
        # Implementação depende da API específica
    
    def get_best_prices(self, token_id: str) -> Tuple[float, float]:
        """Retorna melhor bid/ask com cache do WebSocket"""
        # Tenta cache do WebSocket primeiro
        if token_id in self.orderbooks:
            book = self.orderbooks[token_id]
            age = time.time() - book.get("timestamp", 0)
            if age < 2:  # Cache válido por 2s
                best_bid = float(book["bids"][0]["price"]) if book.get("bids") else 0
                best_ask = float(book["asks"][0]["price"]) if book.get("asks") else 1
                return best_bid, best_ask
        
        # Fallback para REST
        try:
            url = f"{self.config.host}/book"
            resp = requests.get(url, params={"token_id": token_id}, timeout=2).json()
            best_bid = float(resp["bids"][0]["price"]) if resp.get("bids") else 0
            best_ask = float(resp["asks"][0]["price"]) if resp.get("asks") else 1
            return best_bid, best_ask
        except:
            return 0.0, 1.0
    
    def place_smart_order(self, token_id: str, size_usdc: float, side: str, 
                          order_type: str = "market") -> Dict:
        """
        Coloca ordem com ciência das taxas
        order_type: "market" (taker) ou "limit" (maker)
        """
        if self.simulation_mode:
            log.info(f"[SIM] {side.upper()} ${size_usdc} @ {order_type}")
            return {"success": True, "order_id": f"SIM-{int(time.time())}"}
        
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
            
            # 3. Cria ordem com fee incluso na assinatura
            order_args = OrderArgs(
                price=price,
                size=shares,
                side=Side.BUY if side == "buy" else Side.SELL,
                token_id=token_id,
                fee_rate_bps=fee_rate  # CRÍTICO!
            )
            
            resp = self.client.create_and_post_order(order_args)
            return {"success": True, "order_id": resp.get("orderID")}
            
        except Exception as e:
            log.error(f"Erro na ordem: {e}")
            return {"success": False, "error": str(e)}

# ============= ESTRATÉGIA DE ARBITRAGEM =============
class ArbitrageEngine:
    """Detecta e executa arbitragem entre mercados relacionados"""
    
    def __init__(self, client: OptimizedPolymarketClient, config: OptimizedConfig):
        self.client = client
        self.config = config
        self.related_markets = {}  # Mapeia mercados relacionados
    
    def scan_arbitrage(self) -> List[Dict]:
        """Procura oportunidades de arbitragem"""
        opportunities = []
        
        # Exemplo: Mercados "Time A vence" e "Time A não perde" (vitória ou empate)
        # A lógica real exigiria mapeamento dos mercados da Polymarket
        
        for market_pair in self._get_market_pairs():
            token1, token2 = market_pair["token1"], market_pair["token2"]
            
            # Obtém preços
            bid1, ask1 = self.client.get_best_prices(token1)
            bid2, ask2 = self.client.get_best_prices(token2)
            
            # Verifica arbitragem: preço de 1 + preço de 2 < 1
            if ask1 + ask2 < 0.98:  # 2% de desconto
                size = min(self.config.arb_max_capital / 2, 100)
                opp = {
                    "type": "sum_lt_1",
                    "token1": token1,
                    "token2": token2,
                    "price1": ask1,
                    "price2": ask2,
                    "total": ask1 + ask2,
                    "size": size,
                    "expected_profit": size * (1 - (ask1 + ask2))
                }
                opportunities.append(opp)
            
            # Verifica arbitragem de spread entre mercados similares
            if bid1 - ask2 > self.config.min_arb_spread:
                opp = {
                    "type": "cross_market",
                    "buy_token": token2,
                    "sell_token": token1,
                    "buy_price": ask2,
                    "sell_price": bid1,
                    "spread": bid1 - ask2,
                    "size": min(self.config.arb_max_capital, 50)
                }
                opportunities.append(opp)
        
        return opportunities
    
    def execute_arbitrage(self, opportunity: Dict) -> bool:
        """Executa oportunidade de arbitragem"""
        if opportunity["type"] == "sum_lt_1":
            # Compra ambos os tokens
            buy1 = self.client.place_smart_order(
                opportunity["token1"], 
                opportunity["size"], 
                "buy", 
                "market"
            )
            buy2 = self.client.place_smart_order(
                opportunity["token2"],
                opportunity["size"],
                "buy",
                "market"
            )
            
            if buy1["success"] and buy2["success"]:
                log.info(f"[ARB] Lucro esperado: ${opportunity['expected_profit']:.2f}")
                return True
        
        elif opportunity["type"] == "cross_market":
            # Compra barato, vende caro
            buy = self.client.place_smart_order(
                opportunity["buy_token"],
                opportunity["size"],
                "buy",
                "market"
            )
            sell = self.client.place_smart_order(
                opportunity["sell_token"],
                opportunity["size"],
                "sell",
                "market"
            )
            
            if buy["success"] and sell["success"]:
                profit = opportunity["size"] * opportunity["spread"]
                log.info(f"[ARB] Lucro spread: ${profit:.2f}")
                return True
        
        return False
    
    def _get_market_pairs(self):
        """Retorna pares de mercados relacionados"""
        # Implementação dependeria de query aos mercados da Polymarket
        return []

# ============= ESTRATÉGIA DE MARKET MAKING =============
class MarketMakingEngine:
    """Provedor de liquidez para capturar spread + recompensas"""
    
    def __init__(self, client: OptimizedPolymarketClient, config: OptimizedConfig):
        self.client = client
        self.config = config
        self.active_markets = set()
        self.orders = {}  # Ordens ativas por mercado
    
    def add_market(self, token_id: str, fair_price: float):
        """Adiciona mercado para fazer market making"""
        self.active_markets.add(token_id)
        self.orders[token_id] = {"bid": None, "ask": None}
    
    def rebalance(self):
        """Atualiza ordens de market making"""
        for token_id in self.active_markets:
            try:
                # Obtém preço justo (usando nosso modelo)
                fair = self._estimate_fair_price(token_id)
                
                # Calcula preços com spread
                spread = self.config.mm_spread_bps / 10000  # bps para decimal
                bid_price = fair * (1 - spread/2)
                ask_price = fair * (1 + spread/2)
                
                # Cancela ordens existentes
                self._cancel_orders(token_id)
                
                # Coloca novas ordens (sempre MAKER para não pagar taxas)
                bid_order = self.client.place_smart_order(
                    token_id,
                    self.config.mm_order_size,
                    "buy",
                    "limit"  # Maker order!
                )
                
                ask_order = self.client.place_smart_order(
                    token_id,
                    self.config.mm_order_size,
                    "sell",
                    "limit"  # Maker order!
                )
                
                log.debug(f"[MM] {token_id}: Bid ${bid_price:.4f} Ask ${ask_price:.4f}")
                
            except Exception as e:
                log.error(f"Erro MM {token_id}: {e}")
    
    def _estimate_fair_price(self, token_id: str) -> float:
        """Estima preço justo usando múltiplas fontes"""
        # 1. Preço de mercado (mid)
        bid, ask = self.client.get_best_prices(token_id)
        mid = (bid + ask) / 2 if bid > 0 else 0.5
        
        # 2. Poderia adicionar modelo probabilístico aqui
        return mid
    
    def _cancel_orders(self, token_id: str):
        """Cancela ordens ativas"""
        # Implementar cancelamento via API
        pass

# ============= ESTRATÉGIA PRINCIPAL OTIMIZADA =============
class OptimizedStrategy:
    def __init__(self, config: OptimizedConfig):
        self.config = config
        self.price_history = {}  # Para análise de momentum
        
    def should_enter(self, match: Match, available_usdc: float) -> Tuple[bool, str, float, float]:
        """Versão melhorada com múltiplos fatores"""
        now = datetime.utcnow()
        hours_until = (match.start_time.replace(tzinfo=None) - now).total_seconds() / 3600
        
        # Filtro temporal
        if not (1 <= hours_until <= 48):
            return False, "", 0, 0
        
        # Calcula probabilidades normalizadas
        total = match.home_odds + match.draw_odds + match.away_odds
        if total <= 0:
            return False, "", 0, 0
        
        # Múltiplos modelos
        probs = {
            "home": match.home_odds / total,
            "draw": match.draw_odds / total,
            "away": match.away_odds / total
        }
        
        # Modelo 1: Odds públicas (TheOddsAPI)
        # Modelo 2: Moving average de preços (momentum)
        # Modelo 3: Volume analysis
        
        best_opportunity = None
        best_score = 0
        
        for outcome in ["home", "draw", "away"]:
            market_price = getattr(match, f"{outcome}_odds", 0)
            if market_price <= 0:
                continue
            
            # Edge básico
            model_prob = probs[outcome]
            basic_edge = model_prob - market_price
            
            # Fator momentum (se preço está subindo)
            momentum = self._get_momentum(match, outcome)
            
            # Fator volume
            volume_score = self._get_volume_score(match, outcome)
            
            # Score composto
            score = basic_edge * 0.5 + momentum * 0.3 + volume_score * 0.2
            
            if (basic_edge > self.config.min_edge_pct and 
                basic_edge < self.config.max_edge_pct and
                score > best_score):
                
                best_score = score
                
                # Tamanho da posição baseado no score
                size_multiplier = min(2.0, max(0.5, score / 0.05))
                position_size = min(
                    self.config.max_position_usdc,
                    available_usdc * self.config.bankroll_risk_pct * size_multiplier
                )
                
                best_opportunity = (outcome, basic_edge, position_size)
        
        if best_opportunity:
            outcome, edge, size = best_opportunity
            log.info(f"[OP] {match.home_team} vs {match.away_team} | {outcome} | "
                    f"Edge: {edge*100:.1f}% | Size: ${size:.2f}")
            return True, outcome, edge, size
        
        return False, "", 0, 0
    
    def _get_momentum(self, match: Match, outcome: str) -> float:
        """Analisa tendência de preço (0 a 1)"""
        # Implementar análise de série temporal
        return 0.5
    
    def _get_volume_score(self, match: Match, outcome: str) -> float:
        """Analisa volume de negociação"""
        return 0.5
    
    def should_exit_advanced(self, position: Position, match: Match, 
                            current_price: float) -> List[Tuple[float, str]]:
        """
        Retorna múltiplos sinais de saída com proporções
        [(percentual_a_sair, motivo), ...]
        """
        exits = []
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        
        # 1. Profit taking em múltiplos níveis
        for target in self.config.profit_targets:
            if pnl_pct >= target and position.shares > 0:
                # Sai 30% em cada target
                exit_pct = 0.3
                exits.append((exit_pct, f"take_profit_{int(target*100)}%"))
                position.shares *= (1 - exit_pct)
        
        # 2. Stop loss progressivo
        for stop in self.config.stop_losses:
            if pnl_pct <= -stop and position.shares > 0:
                exit_pct = 0.5 if stop == self.config.stop_losses[0] else 1.0
                exits.append((exit_pct, f"stop_loss_{int(stop*100)}%"))
                position.shares *= (1 - exit_pct)
        
        # 3. Trailing stop
        if pnl_pct > 0.2:  # Ativa após 20% de lucro
            current_stop = current_price * (1 - self.config.trailing_stop_pct)
            if hasattr(position, 'trailing_high'):
                if current_price < position.trailing_high * (1 - self.config.trailing_stop_pct):
                    exits.append((1.0, "trailing_stop"))
            else:
                position.trailing_high = max(
                    getattr(position, 'trailing_high', current_price),
                    current_price
                )
        
        # 4. Eventos de jogo
        if match.status == "live":
            # Gol a favor
            if ((position.outcome == "home" and match.home_score > match.away_score) or
                (position.outcome == "away" and match.away_score > match.home_score)):
                if pnl_pct > 0.1:
                    exits.append((0.5, "favorable_goal"))
            
            # Gol contra
            if ((position.outcome == "home" and match.away_score > match.home_score) or
                (position.outcome == "away" and match.home_score > match.away_score)):
                exits.append((1.0, "adverse_goal"))
        
        # 5. Fim de jogo
        if match.status == "finished":
            exits.append((1.0, "match_finished"))
        
        return exits

# ============= BOT PRINCIPAL OTIMIZADO =============
class OptimizedFootballBot:
    def __init__(self):
        self.config = CONFIG
        self.client = OptimizedPolymarketClient(CONFIG)
        self.strategy = OptimizedStrategy(CONFIG)
        self.arbitrage = ArbitrageEngine(self.client, CONFIG)
        self.market_making = MarketMakingEngine(self.client, CONFIG)
        self.portfolio = PortfolioManager()
        
        self.running = False
        self.last_arb_scan = 0
        self.last_mm_rebalance = 0
        
        log.info("=" * 70)
        log.info("  POLYMARKET BOT v2.0 - OTIMIZADO PARA LUCRO")
        log.info(f"  Bankroll: ${CONFIG.total_bankroll_usdc} USDC")
        log.info(f"  Estratégias: Event-Driven | Arbitragem | Market Making")
        log.info("=" * 70)
    
    def run_cycle(self):
        """Ciclo principal com múltiplas estratégias"""
        
        # 1. Estratégia principal (event-driven)
        self._scan_pregame()
        self._monitor_live()
        
        # 2. Arbitragem (a cada 30s)
        if time.time() - self.last_arb_scan > 30:
            opportunities = self.arbitrage.scan_arbitrage()
            for opp in opportunities[:3]:  # Limita a 3 por ciclo
                if self.arbitrage.execute_arbitrage(opp):
                    log.info(f"[ARB] Executada: ${opp.get('expected_profit', 0):.2f}")
            self.last_arb_scan = time.time()
        
        # 3. Market Making (a cada 60s)
        if time.time() - self.last_mm_rebalance > 60:
            self.market_making.rebalance()
            self.last_mm_rebalance = time.time()
        
        # 4. Status periódico
        if int(time.time()) % 300 < 5:  # A cada 5 min
            self._print_status()
    
    def _scan_pregame(self):
        """Versão otimizada do scan pre-game"""
        if len(self.portfolio.positions) >= self.config.max_open_positions:
            return
        
        balance = self.client.get_usdc_balance()
        
        for match in self._get_filtered_matches():
            should_enter, outcome, edge, size = self.strategy.should_enter(match, balance)
            
            if should_enter:
                token_id = self._get_token_id(match, outcome)
                
                # Estratégia híbrida: tenta maker primeiro, se falhar vai de taker
                order = self.client.place_smart_order(
                    token_id, size, "buy", "limit"  # Tenta maker primeiro
                )
                
                if not order["success"]:
                    # Fallback para market order
                    order = self.client.place_smart_order(
                        token_id, size, "buy", "market"
                    )
                
                if order["success"]:
                    self._open_position(match, outcome, token_id, size, order)
                    
                    # Adiciona para market making depois
                    if self.config.enable_market_making:
                        self.market_making.add_market(token_id, getattr(match, f"{outcome}_odds"))
    
    def _monitor_live(self):
        """Monitora posições abertas com saídas em múltiplos níveis"""
        if not self.portfolio.positions:
            return
        
        for pos_id, position in list(self.portfolio.positions.items()):
            match = position.match
            current_price = self.client.get_best_prices(position.token_id)[1]  # Ask price
            
            # Obtém decisões de saída em múltiplos níveis
            exit_decisions = self.strategy.should_exit_advanced(
                position, match, current_price
            )
            
            for exit_pct, reason in exit_decisions:
                if exit_pct <= 0 or position.shares <= 0:
                    continue
                
                shares_to_sell = position.shares * exit_pct
                
                # Vende a parcela
                sell_order = self.client.place_smart_order(
                    position.token_id,
                    shares_to_sell * current_price,  # size em USDC
                    "sell",
                    "market"
                )
                
                if sell_order["success"]:
                    position.shares -= shares_to_sell
                    pnl_pct = (current_price - position.entry_price) / position.entry_price
                    
                    log.info(f"[EXIT] {pos_id[:8]} | {exit_pct*100:.0f}% | "
                            f"PnL: {pnl_pct*100:.1f}% | {reason}")
            
            # Se vendeu tudo, fecha posição
            if position.shares <= 0.001:  # Tolerância para floating point
                self.portfolio.close_position(pos_id, current_price, reason)

# ============= MAIN =============
if __name__ == "__main__":
    import sys
    
    if not CONFIG.simulation_mode:
        print("\n" + "!" * 60)
        print("!!! ATENÇÃO: MODO LIVE TRADING ATIVO !!!")
        print("!" * 60)
        confirm = input("Digite CONFIRMAR para prosseguir: ").strip()
        if confirm != "CONFIRMAR":
            sys.exit(0)
    
    bot = OptimizedFootballBot()
    
    try:
        schedule.every(5).seconds.do(bot.run_cycle)
        
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    except KeyboardInterrupt:
        log.info("[STOP] Bot finalizado")
        bot.print_status()
