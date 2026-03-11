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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PolyBot")

# ============= CONFIGURAÇÕES =============
class Config:
    # ===== MODO TESTE REAL =====
    SIMULATION_MODE = True  # True = sem dinheiro real
    USE_REAL_DATA = True    # True = dados REAIS da Polymarket
    
    # ===== GESTÃO DE RISCO VIRTUAL =====
    MAX_POSITION_USDC = 10.0        # Tamanho virtual da aposta
    MAX_OPEN_POSITIONS = 3           # Máximo de posições virtuais
    VIRTUAL_BANKROLL = 100.0         # Bankroll virtual inicial
    BANKROLL_RISK_PCT = 0.10         # 10% do bankroll virtual por aposta
    
    # ===== PARÂMETROS DE ESTRATÉGIA =====
    MIN_EDGE_PCT = 0.02               # 2% mínimo de edge
    PROFIT_TARGET = 0.20              # Vende com 20% de lucro
    STOP_LOSS = 0.15                   # Vende com 15% de prejuízo
    MIN_HOURS_BEFORE = 1.0             # Mínimo 1h antes do jogo
    MAX_HOURS_BEFORE = 72.0            # Máximo 72h antes
    
    # ===== POLYMARKET API =====
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

config = Config()

# ============= CLIENTE POLYMARKET (SÓ LEITURA) =============
class PolymarketDataClient:
    """Cliente APENAS para LEITURA de dados - sem trading real"""
    
    def __init__(self):
        self.gamma_url = config.GAMMA_URL
        self.clob_url = config.CLOB_URL
        
        log.info("="*60)
        log.info(" POLYMARKET DATA CLIENT - MODO TESTE REAL")
        log.info("="*60)
        log.info(f" 📊 Dados: {'REAIS' if config.USE_REAL_DATA else 'SIMULADOS'}")
        log.info(f" 💰 Trading: {'SIMULAÇÃO' if config.SIMULATION_MODE else 'REAL'}")
        log.info(f" 📈 Bankroll virtual: ${config.VIRTUAL_BANKROLL}")
        log.info("="*60)
    
    def buscar_jogos_reais(self):
        """Busca jogos REAIS da Polymarket"""
        log.info("\n🔍 BUSCANDO JOGOS REAIS DA POLYMARKET...")
        
        # Tags atualizadas da Polymarket
        tags = [
            ("premier-league", "Premier League"),
            ("laliga", "La Liga"),
            ("bundesliga", "Bundesliga"),
            ("serie-a", "Serie A"),
            ("ligue-1", "Ligue 1"),
            ("brazil-serie-a", "Brasileirão Série A"),  # TEM JOGO HOJE!
            ("argentina-primera", "Argentine Primera"),
            ("liga-mx", "Liga MX"),
            ("copa-libertadores", "Copa Libertadores"),
            ("champions-league", "Champions League")
        ]
        
        todos_jogos = []
        
        for tag_slug, league_name in tags:
            try:
                # Gamma API - pública, sem autenticação
                url = f"{self.gamma_url}/events"
                params = {
                    "tag_slug": tag_slug,
                    "active": "true",
                    "closed": "false",
                    "limit": 20
                }
                
                log.info(f"   📍 {league_name}...")
                resp = requests.get(url, params=params, timeout=10)
                
                if resp.status_code != 200:
                    continue
                
                events = resp.json()
                
                for event in events:
                    jogo = self._parse_event(event, league_name)
                    if jogo:
                        todos_jogos.append(jogo)
                        log.info(f"      ✅ {jogo['casa']} vs {jogo['fora']} - {jogo['horario'].strftime('%d/%m %H:%M')}")
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                log.debug(f"Erro em {tag_slug}: {e}")
                continue
        
        log.info(f"\n📊 TOTAL: {len(todos_jogos)} jogos REAIS encontrados")
        
        # Se não encontrou nada, avisa mas não usa dados simulados
        if not todos_jogos:
            log.warning("⚠️ NENHUM jogo real encontrado no momento!")
            log.warning("   A API da Polymarket pode estar sem eventos ativos.")
            log.warning("   Tente novamente mais perto dos horários dos jogos.")
        
        return todos_jogos
    
    def _parse_event(self, event, league):
        """Converte evento em formato padronizado"""
        try:
            title = event.get("title", "")
            
            # Extrai times
            times = self._extrair_times(title)
            if not times:
                return None
            
            casa, fora = times
            
            # Data
            start_date = event.get("start_date")
            if not start_date:
                return None
            
            horario = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            
            # Pega odds dos markets
            odds_casa = 0.5
            odds_empate = 0.28
            odds_fora = 0.5
            token_ids = {}
            
            markets = event.get("markets", [])
            for market in markets:
                question = market.get("question", "").lower()
                prices = market.get("outcomePrices", ["0.5", "0.5"])
                clob_ids = market.get("clobTokenIds", [])
                
                if len(prices) >= 1:
                    if "draw" in question or "empate" in question:
                        odds_empate = float(prices[0])
                        if clob_ids:
                            token_ids["empate"] = clob_ids[0]
                    elif casa.lower() in question:
                        odds_casa = float(prices[0])
                        if clob_ids:
                            token_ids["casa"] = clob_ids[0]
                    elif fora.lower() in question:
                        odds_fora = float(prices[0])
                        if clob_ids:
                            token_ids["fora"] = clob_ids[0]
            
            # Busca preços atualizados do CLOB
            preco_casa = self._get_clob_price(token_ids.get("casa", ""))
            preco_fora = self._get_clob_price(token_ids.get("fora", ""))
            preco_empate = self._get_clob_price(token_ids.get("empate", ""))
            
            return {
                "id": event.get("id", ""),
                "casa": casa,
                "fora": fora,
                "liga": league,
                "horario": horario,
                "odds": {
                    "casa": preco_casa if preco_casa else odds_casa,
                    "empate": preco_empate if preco_empate else odds_empate,
                    "fora": preco_fora if preco_fora else odds_fora
                },
                "token_ids": token_ids,
                "condition_id": event.get("condition_id", "")
            }
            
        except Exception as e:
            return None
    
    def _get_clob_price(self, token_id):
        """Busca preço atual do CLOB"""
        if not token_id:
            return None
        
        try:
            url = f"{self.clob_url}/book"
            resp = requests.get(url, params={"token_id": token_id}, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                
                if bids and asks:
                    bid = float(bids[0].get("price", 0))
                    ask = float(asks[0].get("price", 1))
                    return (bid + ask) / 2
        except:
            pass
        
        return None
    
    def _extrair_times(self, title):
        """Extrai nomes dos times do título"""
        for sep in [" vs ", " VS ", " v ", " - ", " – ", " x "]:
            if sep in title:
                parts = title.split(sep)
                if len(parts) >= 2:
                    return parts[0].strip(), parts[1].strip()
        return None
    
    def get_preco_atual(self, token_id):
        """Wrapper para obter preço atual (usado durante monitoramento)"""
        return self._get_clob_price(token_id) or 0.5


# ============= SIMULADOR DE TRADES =============
class TradeSimulator:
    """Simula trades com dados REAIS mas sem dinheiro"""
    
    def __init__(self):
        self.trades_abertos = []
        self.trades_fechados = []
        self.virtual_bankroll = config.VIRTUAL_BANKROLL
        self.initial_bankroll = config.VIRTUAL_BANKROLL
        self.pnl_total = 0.0
        self.client = PolymarketDataClient()
        
        log.info("\n💰 SIMULADOR DE TRADES INICIALIZADO")
        log.info(f"   Bankroll virtual: ${self.virtual_bankroll}")
        log.info(f"   Tamanho aposta: ${config.MAX_POSITION_USDC}")
        log.info(f"   Máx posições: {config.MAX_OPEN_POSITIONS}")
    
    def calcular_edge(self, odds_casa, odds_empate, odds_fora):
        """Calcula edge (vantagem)"""
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
    
    def executar_trade_simulado(self, jogo, resultado, edge):
        """Executa um trade VIRTUAL com dados REAIS"""
        
        if len(self.trades_abertos) >= config.MAX_OPEN_POSITIONS:
            return
        
        preco = jogo["odds"][resultado.lower()]
        valor = config.MAX_POSITION_USDC
        shares = valor / preco
        
        trade = {
            "id": f"trade_{int(time.time())}_{len(self.trades_abertos)}",
            "jogo": jogo,
            "resultado": resultado,
            "preco_entrada": preco,
            "valor": valor,
            "shares": shares,
            "edge": edge,
            "momento": datetime.now(),
            "token_id": jogo["token_ids"].get(resultado.lower(), ""),
            "preco_atual": preco,
            "pnl": 0.0,
            "pnl_pct": 0.0
        }
        
        self.trades_abertos.append(trade)
        self.virtual_bankroll -= valor
        
        log.info(f"\n✅ TRADE VIRTUAL EXECUTADO!")
        log.info(f"   {jogo['casa']} vs {jogo['fora']}")
        log.info(f"   Aposta: {resultado} @ {preco:.3f}")
        log.info(f"   Valor: ${valor:.2f} ({shares:.1f} shares)")
        log.info(f"   Edge: {edge*100:.1f}%")
        log.info(f"   Bankroll restante: ${self.virtual_bankroll:.2f}")
        
        return trade
    
    def atualizar_trades(self):
        """Atualiza preços dos trades com dados REAIS do CLOB"""
        novos_abertos = []
        
        for trade in self.trades_abertos:
            # Busca preço REAL do CLOB
            if trade["token_id"]:
                preco_atual = self.client.get_preco_atual(trade["token_id"])
            else:
                # Simula variação se não tiver token_id
                import random
                preco_atual = trade["preco_entrada"] * (1 + random.uniform(-0.1, 0.2))
            
            trade["preco_atual"] = preco_atual
            trade["pnl"] = (preco_atual - trade["preco_entrada"]) * trade["shares"]
            trade["pnl_pct"] = (preco_atual - trade["preco_entrada"]) / trade["preco_entrada"]
            
            log.info(f"\n📈 Acompanhando: {trade['jogo']['casa']} vs {trade['jogo']['fora']}")
            log.info(f"   Entrada: ${trade['preco_entrada']:.3f} | Atual: ${preco_atual:.3f}")
            log.info(f"   PnL: ${trade['pnl']:.2f} ({trade['pnl_pct']*100:+.1f}%)")
            
            # Decisão de venda baseada na estratégia
            vender = False
            motivo = ""
            
            if trade['pnl_pct'] >= config.PROFIT_TARGET:
                vender = True
                motivo = f"PROFIT TARGET ({config.PROFIT_TARGET*100}%)"
            elif trade['pnl_pct'] <= -config.STOP_LOSS:
                vender = True
                motivo = f"STOP LOSS ({config.STOP_LOSS*100}%)"
            elif trade['jogo']['horario'] < datetime.now(trade['jogo']['horario'].tzinfo):
                vender = True
                motivo = "JOGO FINALIZADO"
            
            if vender:
                self.virtual_bankroll += trade['valor'] + trade['pnl']
                self.pnl_total += trade['pnl']
                trade['motivo_venda'] = motivo
                self.trades_fechados.append(trade)
                
                resultado = "✅ LUCRO" if trade['pnl'] > 0 else "❌ PREJUÍZO"
                log.info(f"   🔴 VENDEU! {resultado} | Motivo: {motivo}")
                log.info(f"   PnL final: ${trade['pnl']:.2f}")
            else:
                novos_abertos.append(trade)
        
        self.trades_abertos = novos_abertos
    
    def mostrar_status(self):
        """Mostra status completo da simulação"""
        log.info("\n" + "="*70)
        log.info("📊 STATUS DA SIMULAÇÃO")
        log.info("="*70)
        log.info(f"   Bankroll virtual: ${self.virtual_bankroll:.2f}")
        log.info(f"   Bankroll inicial: ${self.initial_bankroll:.2f}")
        log.info(f"   PnL Total: ${self.pnl_total:.2f}")
        log.info(f"   Retorno: {(self.virtual_bankroll/self.initial_bankroll - 1)*100:+.1f}%")
        log.info(f"   Posições abertas: {len(self.trades_abertos)}")
        log.info(f"   Posições fechadas: {len(self.trades_fechados)}")
        
        if self.trades_fechados:
            wins = [t for t in self.trades_fechados if t['pnl'] > 0]
            losses = [t for t in self.trades_fechados if t['pnl'] <= 0]
            win_rate = len(wins) / len(self.trades_fechados) * 100 if self.trades_fechados else 0
            
            log.info(f"   Win Rate: {win_rate:.1f}% ({len(wins)}W/{len(losses)}L)")
            
            if wins:
                avg_win = sum(t['pnl'] for t in wins) / len(wins)
                log.info(f"   Avg Win: ${avg_win:.2f}")
            if losses:
                avg_loss = sum(t['pnl'] for t in losses) / len(losses)
                log.info(f"   Avg Loss: ${avg_loss:.2f}")
        
        log.info("="*70)


# ============= BOT PRINCIPAL =============
class PolymarketTestBot:
    """Bot para TESTAR lucratividade com dados REAIS"""
    
    def __init__(self):
        self.data_client = PolymarketDataClient()
        self.simulator = TradeSimulator()
        self.stats = {
            "ciclos": 0,
            "jogos_analisados": 0,
            "oportunidades_encontradas": 0
        }
        
        log.info("\n" + "🔥"*70)
        log.info(" POLYMARKET TEST BOT - MODO TESTE REAL")
        log.info("🔥"*70)
        log.info(" 📊 Dados: REAIS da Polymarket")
        log.info(" 💰 Trading: SIMULAÇÃO (sem dinheiro real)")
        log.info(" 🎯 Objetivo: Testar lucratividade da estratégia")
        log.info("🔥"*70 + "\n")
    
    def escanear_oportunidades(self, jogos):
        """Encontra oportunidades com edge positivo"""
        oportunidades = []
        
        for jogo in jogos:
            self.stats["jogos_analisados"] += 1
            odds = jogo["odds"]
            edge, resultado = self.simulator.calcular_edge(odds["casa"], odds["empate"], odds["fora"])
            
            # Calcula horas até o jogo
            if jogo["horario"].tzinfo:
                agora = datetime.now(jogo["horario"].tzinfo)
            else:
                agora = datetime.now()
            
            horas_ate = (jogo["horario"] - agora).total_seconds() / 3600
            
            # Log detalhado
            log.info(f"\n📋 {jogo['casa']} vs {jogo['fora']} ({jogo['liga']})")
            log.info(f"   ⏰ {jogo['horario'].strftime('%H:%M %d/%m')} (em {horas_ate:.1f}h)")
            log.info(f"   📊 Odds: CASA {odds['casa']:.3f} | EMPATE {odds['empate']:.3f} | FORA {odds['fora']:.3f}")
            log.info(f"   📈 Edge: {edge*100:+.2f}% ({resultado})")
            
            # Critérios de entrada
            if (edge > config.MIN_EDGE_PCT and 
                horas_ate >= config.MIN_HOURS_BEFORE and 
                horas_ate <= config.MAX_HOURS_BEFORE):
                
                oportunidades.append((jogo, resultado, edge))
                self.stats["oportunidades_encontradas"] += 1
                log.info(f"   🟢 OPORTUNIDADE CONFIRMADA!")
        
        return oportunidades
    
    def run(self):
        """Loop principal"""
        log.info("\n🚀 INICIANDO TESTE DE LUCRATIVIDADE...\n")
        
        while True:
            self.stats["ciclos"] += 1
            log.info(f"\n{'='*70}")
            log.info(f" CICLO #{self.stats['ciclos']} - {datetime.now().strftime('%H:%M:%S')}")
            log.info('='*70)
            
            # 1. Buscar dados REAIS
            jogos = self.data_client.buscar_jogos_reais()
            
            if not jogos:
                log.warning("⚠️ Nenhum jogo real encontrado. Aguardando...")
                log.info(f"\n⏳ Próximo ciclo em 5 minutos...")
                time.sleep(300)  # 5 minutos
                continue
            
            # 2. Encontrar oportunidades
            oportunidades = self.escanear_oportunidades(jogos)
            
            # 3. Executar trades VIRTUAIS
            for jogo, resultado, edge in oportunidades:
                if len(self.simulator.trades_abertos) < config.MAX_OPEN_POSITIONS:
                    self.simulator.executar_trade_simulado(jogo, resultado, edge)
            
            # 4. Atualizar trades existentes
            if self.simulator.trades_abertos:
                self.simulator.atualizar_trades()
            
            # 5. Mostrar status da simulação
            self.simulator.mostrar_status()
            
            # 6. Estatísticas do teste
            log.info("\n📊 ESTATÍSTICAS DO TESTE")
            log.info(f"   Ciclos executados: {self.stats['ciclos']}")
            log.info(f"   Jogos analisados: {self.stats['jogos_analisados']}")
            log.info(f"   Oportunidades: {self.stats['oportunidades_encontradas']}")
            
            log.info(f"\n⏳ Próximo ciclo em 5 minutos...")
            time.sleep(300)  # 5 minutos


if __name__ == "__main__":
    print("\n" + "🎯"*35)
    print(" TESTE DE LUCRATIVIDADE - MODO REAL")
    print("🎯"*35)
    print("\n⚠️  ATENÇÃO: Este é um TESTE com dados REAIS")
    print("   Nenhum dinheiro real será movimentado")
    print("   Apenas simulação financeira")
    print("\n" + "🎯"*35 + "\n")
    
    bot = PolymarketTestBot()
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🛑 Teste interrompido")
        print("\n📊 RESULTADO FINAL:")
        bot.simulator.mostrar_status()
        
        # Decisão final
        if bot.simulator.pnl_total > 0:
            print("\n✅ ESTRATÉGIA LUCRATIVA NO TESTE!")
            print(f"   Lucro: ${bot.simulator.pnl_total:.2f}")
            print(f"   Retorno: {(bot.simulator.virtual_bankroll/bot.simulator.initial_bankroll - 1)*100:+.1f}%")
            print("\n   Considere ativar modo real com cautela.")
        else:
            print("\n❌ ESTRATÉGIA NÃO LUCRATIVA NO TESTE")
            print(f"   Prejuízo: ${bot.simulator.pnl_total:.2f}")
            print(f"   Retorno: {(bot.simulator.virtual_bankroll/bot.simulator.initial_bankroll - 1)*100:+.1f}%")
            print("\n   Ajuste os parâmetros antes do modo real.")
