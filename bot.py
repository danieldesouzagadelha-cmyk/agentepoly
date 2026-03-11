"""
POLYMARKET BOT - VERSÃO COMPLETA
"""

import os
import time
import logging
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("Bot")

class PolymarketBot:
    def __init__(self):
        self.contador = 0
        self.trades_abertos = []
        self.trades_fechados = []
        self.pnl_total = 0.0
        self.jogos = self.criar_muitos_jogos()
        
        log.info("="*70)
        log.info("🚀 BOT INICIADO COM SUCESSO!")
        log.info(f"📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        log.info(f"📊 Total de jogos disponíveis: {len(self.jogos)}")
        log.info("="*70)
    
    def criar_muitos_jogos(self):
        """Cria 20 jogos simulados para teste"""
        agora = datetime.now()
        times = [
            ("Arsenal", "Chelsea", 0.45, 0.28, 0.27),
            ("Liverpool", "Man City", 0.38, 0.27, 0.35),
            ("Barcelona", "Real Madrid", 0.48, 0.25, 0.27),
            ("Bayern", "Dortmund", 0.52, 0.24, 0.24),
            ("Flamengo", "Palmeiras", 0.42, 0.28, 0.30),
            ("Manchester United", "Tottenham", 0.44, 0.27, 0.29),
            ("Juventus", "Milan", 0.41, 0.29, 0.30),
            ("PSG", "Marseille", 0.55, 0.23, 0.22),
            ("Ajax", "PSV", 0.47, 0.26, 0.27),
            ("Benfica", "Porto", 0.43, 0.28, 0.29),
            ("Inter", "Roma", 0.46, 0.27, 0.27),
            ("Atletico", "Sevilla", 0.44, 0.28, 0.28),
            ("Leipzig", "Leverkusen", 0.48, 0.25, 0.27),
            ("Napoli", "Lazio", 0.47, 0.26, 0.27),
            ("Celtic", "Rangers", 0.51, 0.24, 0.25),
            ("Boca", "River", 0.44, 0.27, 0.29),
            ("Nacional", "Peñarol", 0.46, 0.27, 0.27),
            ("Corinthians", "São Paulo", 0.43, 0.28, 0.29),
            ("Grêmio", "Internacional", 0.45, 0.27, 0.28),
            ("Athletico", "Coritiba", 0.47, 0.26, 0.27)
        ]
        
        jogos = []
        for i, (casa, fora, oc, oe, of) in enumerate(times):
            jogos.append({
                "id": i,
                "casa": casa,
                "fora": fora,
                "liga": ["Premier League", "La Liga", "Bundesliga", "Serie A", "Brasileirão"][i % 5],
                "horario": agora + timedelta(hours=2 + i),
                "odds": {"casa": oc, "empate": oe, "fora": of}
            })
        
        return jogos
    
    def calcular_edge(self, odds_casa, odds_empate, odds_fora):
        """Calcula edge para cada resultado"""
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
    
    def escanear_jogos(self):
        """Escaneia jogos e encontra oportunidades"""
        log.info("\n" + "🔍"*35)
        log.info(" ESCANEANDO JOGOS")
        log.info("🔍"*35)
        
        oportunidades = []
        
        for jogo in random.sample(self.jogos, min(5, len(self.jogos))):
            odds = jogo["odds"]
            edge, resultado = self.calcular_edge(odds["casa"], odds["empate"], odds["fora"])
            
            status = ""
            if edge > 0.02:
                status = "🟢 OPORTUNIDADE!"
                oportunidades.append((jogo, resultado, edge))
            elif edge < -0.02:
                status = "🔴 EVITAR"
            else:
                status = "⚪ NEUTRO"
            
            log.info(f"\n📋 {jogo['casa']} vs {jogo['fora']} ({jogo['liga']})")
            log.info(f"   ⏰ {jogo['horario'].strftime('%H:%M %d/%m')}")
            log.info(f"   📊 Odds: {odds['casa']:.3f} | {odds['empate']:.3f} | {odds['fora']:.3f}")
            log.info(f"   📈 Edge: {edge*100:+.2f}% ({resultado}) {status}")
        
        return oportunidades
    
    def executar_trade(self, jogo, resultado, edge):
        """Executa um trade simulado"""
        preco = jogo["odds"][resultado.lower()]
        valor = 50.0
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
            "preco_atual": preco,
            "pnl": 0.0
        }
        
        self.trades_abertos.append(trade)
        
        log.info(f"\n💰 NOVO TRADE EXECUTADO!")
        log.info(f"   {jogo['casa']} vs {jogo['fora']}")
        log.info(f"   Aposta: {resultado} @ {preco:.3f}")
        log.info(f"   Valor: ${valor:.2f} ({shares:.1f} shares)")
        log.info(f"   Edge: {edge*100:.1f}%")
        
        return trade
    
    def atualizar_trades(self):
        """Atualiza preços dos trades abertos"""
        novos_abertos = []
        
        for trade in self.trades_abertos:
            # Simula variação de preço
            variacao = random.uniform(-0.15, 0.35)
            trade["preco_atual"] = trade["preco_entrada"] * (1 + variacao)
            trade["pnl"] = (trade["preco_atual"] - trade["preco_entrada"]) * trade["shares"]
            
            log.info(f"\n📈 Acompanhando: {trade['jogo']['casa']} vs {trade['jogo']['fora']}")
            log.info(f"   Entrada: ${trade['preco_entrada']:.3f} | Atual: ${trade['preco_atual']:.3f}")
            log.info(f"   PnL: ${trade['pnl']:.2f} ({((trade['preco_atual']/trade['preco_entrada'])-1)*100:+.1f}%)")
            
            # Decide se vende
            if trade['pnl'] > 15 or trade['pnl'] < -8:
                log.info(f"   🔴 VENDEU! Motivo: {'Lucro' if trade['pnl']>0 else 'Stop Loss'}")
                self.trades_fechados.append(trade)
                self.pnl_total += trade['pnl']
            else:
                novos_abertos.append(trade)
        
        self.trades_abertos = novos_abertos
    
    def mostrar_status(self):
        """Mostra status completo do bot"""
        log.info("\n" + "📊"*35)
        log.info(" STATUS DO BOT")
        log.info("📊"*35)
        log.info(f"   Posições abertas: {len(self.trades_abertos)}")
        log.info(f"   Posições fechadas: {len(self.trades_fechados)}")
        log.info(f"   PnL Total: ${self.pnl_total:.2f}")
        
        if self.trades_abertos:
            log.info("\n   📈 POSIÇÕES ABERTAS:")
            for t in self.trades_abertos:
                log.info(f"      {t['jogo']['casa']} vs {t['jogo']['fora']} | {t['resultado']} | PnL: ${t['pnl']:.2f}")
        
        if self.trades_fechados:
            log.info("\n   ✅ ÚLTIMOS FECHADOS:")
            for t in self.trades_fechados[-3:]:
                log.info(f"      {t['jogo']['casa']} vs {t['jogo']['fora']} | PnL: ${t['pnl']:.2f}")
        
        log.info("📊"*35)
    
    def run(self):
        """Loop principal"""
        log.info("\n" + "🚀"*35)
        log.info(" INICIANDO LOOP PRINCIPAL")
        log.info("🚀"*35)
        
        ciclo = 0
        while True:
            ciclo += 1
            log.info(f"\n{'='*70}")
            log.info(f" CICLO #{ciclo} - {datetime.now().strftime('%H:%M:%S')}")
            log.info('='*70)
            
            # 1. Escaneia jogos (a cada 3 ciclos)
            if ciclo % 3 == 1:
                oportunidades = self.escanear_jogos()
                
                # 2. Executa novos trades
                for jogo, resultado, edge in oportunidades[:2]:  # Máx 2 por ciclo
                    if len(self.trades_abertos) < 5:  # Máx 5 simultâneos
                        self.executar_trade(jogo, resultado, edge)
            
            # 3. Atualiza trades existentes
            if self.trades_abertos:
                self.atualizar_trades()
            
            # 4. Mostra status
            self.mostrar_status()
            
            # 5. Aguarda
            log.info(f"\n⏳ Próximo ciclo em 30 segundos...")
            time.sleep(30)

if __name__ == "__main__":
    print("\n" + "🎯"*35)
    print(" POLYMARKET BOT - MODO SIMULAÇÃO")
    print("🎯"*35 + "\n")
    
    bot = PolymarketBot()
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🛑 Bot parado")
        print(f"PnL Final: ${bot.pnl_total:.2f}")
