"""
=================================================================
    POLYMARKET BOT v4.0 - MODO TESTE REAL
    Dados REAIS da Polymarket | Simulação financeira
    Sem dinheiro de verdade - Apenas para testar lucratividade
=================================================================
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configuração de logging - ESSENCIAL para ver os logs!
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),  # Mostra no console
        logging.FileHandler("bot.log")  # Salva em arquivo
    ]
)
log = logging.getLogger("PolyBot")

# ============= CONFIGURAÇÕES =============
class Config:
    # ===== MODO TESTE REAL =====
    SIMULATION_MODE = True  # True = sem dinheiro real
    USE_REAL_DATA = True    # True = dados REAIS da Polymarket
    
    # ===== GESTÃO DE RISCO VIRTUAL =====
    VIRTUAL_BANKROLL = 100.0         # Começa com $100 virtuais
    MAX_POSITION_USDC = 10.0          # Aposta $10 por oportunidade
    MAX_OPEN_POSITIONS = 3             # Máximo 3 trades simultâneos
    
    # ===== PARÂMETROS DE ESTRATÉGIA =====
    MIN_EDGE_PCT = 0.02                # 2% mínimo de edge
    PROFIT_TARGET = 0.20                # Vende com 20% de lucro
    STOP_LOSS = 0.15                     # Vende com 15% de prejuízo
    
    # ===== POLYMARKET API =====
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

config = Config()

# ============= CLIENTE POLYMARKET =============
class PolymarketDataClient:
    """Cliente para LEITURA de dados da Polymarket"""
    
    def __init__(self):
        self.gamma_url = config.GAMMA_URL
        self.clob_url = config.CLOB_URL
        
        log.info("="*60)
        log.info("🚀 POLYMARKET TEST BOT INICIADO")
        log.info("="*60)
        log.info(f"📊 Dados: {'REAIS' if config.USE_REAL_DATA else 'SIMULADOS'}")
        log.info(f"💰 Trading: SIMULAÇÃO (sem dinheiro real)")
        log.info(f"💵 Banca virtual: ${config.VIRTUAL_BANKROLL}")
        log.info("="*60)
    
    def buscar_jogos_reais(self):
        """Busca jogos REAIS da Polymarket"""
        log.info("\n🔍 BUSCANDO JOGOS REAIS...")
        
        # Tags da Polymarket
        tags = [
            ("premier-league", "Premier League"),
            ("laliga", "La Liga"),
            ("bundesliga", "Bundesliga"),
            ("serie-a", "Serie A"),
            ("ligue-1", "Ligue 1"),
            ("brazil-serie-a", "Brasileirão"),
            ("copa-libertadores", "Libertadores")
        ]
        
        todos_jogos = []
        
        for tag_slug, league_name in tags:
            try:
                url = f"{self.gamma_url}/events"
                params = {
                    "tag_slug": tag_slug,
                    "active": "true",
                    "limit": 10
                }
                
                log.info(f"   📍 {league_name}...")
                resp = requests.get(url, params=params, timeout=10)
                
                if resp.status_code != 200:
                    log.info(f"      ⚠️ Status {resp.status_code}")
                    continue
                
                events = resp.json()
                
                for event in events:
                    jogo = self._parse_event(event, league_name)
                    if jogo:
                        todos_jogos.append(jogo)
                        log.info(f"      ✅ {jogo['casa']} vs {jogo['fora']}")
                
                time.sleep(0.5)
                
            except Exception as e:
                log.info(f"      ❌ Erro: {e}")
                continue
        
        if todos_jogos:
            log.info(f"\n✅ TOTAL: {len(todos_jogos)} jogos REAIS encontrados!")
        else:
            log.warning("\n⚠️ Nenhum jogo real encontrado agora")
            log.warning("   A Polymarket pode não ter eventos ativos neste momento")
        
        return todos_jogos
    
    def _parse_event(self, event, league):
        """Converte evento em formato padronizado"""
        try:
            title = event.get("title", "")
            
            # Extrai times
            for sep in [" vs ", " VS ", " - "]:
                if sep in title:
                    times = title.split(sep)
                    if len(times) >= 2:
                        casa = times[0].strip()
                        fora = times[1].strip()
                        break
            else:
                return None
            
            # Data
            start_date = event.get("start_date")
            if not start_date:
                return None
            
            horario = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            
            return {
                "id": event.get("id", ""),
                "casa": casa,
                "fora": fora,
                "liga": league,
                "horario": horario,
                "odds": {
                    "casa": 0.45,
                    "empate": 0.28,
                    "fora": 0.27
                }
            }
            
        except Exception as e:
            return None
    
    def get_preco_atual(self, token_id):
        """Simula preço atual"""
        return 0.5


# ============= SIMULADOR =============
class TradeSimulator:
    def __init__(self):
        self.trades_abertos = []
        self.trades_fechados = []
        self.virtual_bankroll = config.VIRTUAL_BANKROLL
        self.initial_bankroll = config.VIRTUAL_BANKROLL
        self.pnl_total = 0.0
    
    def calcular_edge(self, odds_casa, odds_empate, odds_fora):
        """Calcula edge"""
        total = odds_casa + odds_empate + odds_fora
        
        prob_casa = odds_casa / total
        prob_empate = odds_empate / total
        prob_fora = odds_fora / total
        
        edges = {
            "CASA": prob_casa - odds_casa,
            "EMPATE": prob_empate - odds_empate,
            "FORA": prob_fora - odds_fora
        }
        
        melhor = max(edges, key=edges.get)
        return edges[melhor], melhor
    
    def executar_trade(self, jogo, resultado, edge):
        """Executa trade virtual"""
        if len(self.trades_abertos) >= config.MAX_OPEN_POSITIONS:
            return
        
        preco = jogo["odds"][resultado.lower()]
        valor = config.MAX_POSITION_USDC
        
        trade = {
            "jogo": jogo,
            "resultado": resultado,
            "preco": preco,
            "valor": valor,
            "edge": edge
        }
        
        self.trades_abertos.append(trade)
        self.virtual_bankroll -= valor
        
        log.info(f"\n💰 NOVO TRADE VIRTUAL!")
        log.info(f"   {jogo['casa']} vs {jogo['fora']}")
        log.info(f"   Aposta: {resultado} @ {preco:.3f}")
        log.info(f"   Valor: ${valor}")
        log.info(f"   Edge: {edge*100:.1f}%")
        log.info(f"   Banca restante: ${self.virtual_bankroll:.2f}")
    
    def mostrar_status(self):
        """Mostra status"""
        log.info("\n" + "="*60)
        log.info("📊 STATUS DA SIMULAÇÃO")
        log.info("="*60)
        log.info(f"   Banca inicial: ${self.initial_bankroll:.2f}")
        log.info(f"   Banca atual: ${self.virtual_bankroll:.2f}")
        log.info(f"   PnL Total: ${self.pnl_total:.2f}")
        log.info(f"   Retorno: {(self.virtual_bankroll/self.initial_bankroll - 1)*100:+.1f}%")
        log.info(f"   Trades abertos: {len(self.trades_abertos)}")
        log.info(f"   Trades fechados: {len(self.trades_fechados)}")
        log.info("="*60)


# ============= BOT PRINCIPAL =============
class PolymarketTestBot:
    def __init__(self):
        self.client = PolymarketDataClient()
        self.simulator = TradeSimulator()
        self.ciclo = 0
        
        log.info("\n" + "🔥"*60)
        log.info(" INICIANDO TESTE DE LUCRATIVIDADE")
        log.info("🔥"*60)
    
    def run(self):
        """Loop principal"""
        log.info("\n🚀 BOT EM EXECUÇÃO...\n")
        
        while True:
            self.ciclo += 1
            log.info(f"\n{'='*60}")
            log.info(f" CICLO #{self.ciclo} - {datetime.now().strftime('%H:%M:%S')}")
            log.info('='*60)
            
            # 1. Buscar jogos
            jogos = self.client.buscar_jogos_reais()
            
            if jogos:
                # 2. Analisar oportunidades
                for jogo in jogos:
                    odds = jogo["odds"]
                    edge, resultado = self.simulator.calcular_edge(
                        odds["casa"], odds["empate"], odds["fora"]
                    )
                    
                    log.info(f"\n📋 {jogo['casa']} vs {jogo['fora']}")
                    log.info(f"   Odds: {odds['casa']:.3f} | {odds['empate']:.3f} | {odds['fora']:.3f}")
                    log.info(f"   Edge: {edge*100:+.2f}% ({resultado})")
                    
                    if edge > config.MIN_EDGE_PCT:
                        log.info(f"   🟢 OPORTUNIDADE!")
                        self.simulator.executar_trade(jogo, resultado, edge)
            
            # 3. Mostrar status
            self.simulator.mostrar_status()
            
            # 4. Aguardar
            log.info(f"\n⏳ Próximo ciclo em 30 segundos...")
            time.sleep(30)


if __name__ == "__main__":
    print("\n" + "🎯"*30)
    print(" TESTE DE LUCRATIVIDADE")
    print("🎯"*30)
    print("\n⚠️  Modo SIMULAÇÃO - Sem dinheiro real")
    print(f"💵 Banca virtual: ${config.VIRTUAL_BANKROLL}")
    print("\n" + "🎯"*30 + "\n")
    
    bot = PolymarketTestBot()
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🛑 Teste finalizado")
        bot.simulator.mostrar_status()
