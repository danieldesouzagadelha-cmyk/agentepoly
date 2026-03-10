# ⚽ PolyBot — Polymarket Football Trading Agent

Bot totalmente automático para operar na Polymarket em mercados de futebol.
**Estratégia:** Comprar pré-jogo → Vender durante o jogo em eventos (gols).

---

## 📁 Arquivos

| Arquivo | Descrição |
|---|---|
| `bot.py` | Agente principal de trading |
| `dashboard_server.py` | Interface web de monitoramento |
| `.env` | Suas credenciais (criar manualmente) |

---

## ⚙️ Setup

### 1. Instalar dependências
```bash
pip install py-clob-client web3 requests python-dotenv websocket-client schedule
```

### 2. Criar arquivo `.env`
```env
# Polymarket (obter em: https://docs.polymarket.com)
POLYMARKET_PRIVATE_KEY=0xSUA_CHAVE_PRIVADA_POLYGON
POLYMARKET_WALLET_ADDRESS=0xSEU_ENDERECO_POLYGON

# The Odds API - odds pré-jogo (https://the-odds-api.com - plano grátis disponível)
ODDS_API_KEY=sua_chave_aqui

# Sportradar - placar ao vivo (https://sportradar.com - trial disponível)
# Opcional: sem esta chave o bot usa dados simulados para testes
SPORTRADAR_API_KEY=sua_chave_aqui
```

### 3. Configurar o bot (dentro de `bot.py`)
```python
CONFIG = BotConfig(
    simulation_mode=True,          # ← Mude para False apenas quando pronto!
    total_bankroll_usdc=500.0,     # Seu capital total
    max_position_usdc=50.0,        # Máximo por aposta
    bankroll_risk_pct=0.05,        # Risco 5% do bankroll por bet
    profit_target_pct=0.30,        # Vender ao atingir +30%
    stop_loss_pct=0.40,            # Cortar perda em -40%
    sell_after_minutes=70,         # Vender forçado no minuto 70
)
```

### 4. Rodar o bot
```bash
# Terminal 1: Bot de trading
python bot.py

# Terminal 2: Dashboard visual
python dashboard_server.py
# Abrir: http://localhost:8765
```

---

## 🧠 Como funciona

### Fase 1 — Pré-jogo (escaneia a cada 30 min)
1. Busca partidas de futebol na Polymarket e The Odds API
2. Filtra: odds entre 25%-75%, liquidez mínima $1000, jogo em 1-48h
3. Calcula tamanho da posição (Kelly simplificado: 5% do bankroll)
4. Compra automaticamente o token do resultado mais favorável

### Fase 2 — Durante o jogo (monitora a cada 60s)
Vende automaticamente quando qualquer condição for atingida:

| Condição | Ação |
|---|---|
| Time apostado marca gol | Vende (lucro alto esperado) |
| Adversário marca gol | Vende (reduz perda) |
| Preço sobe +30% | Take profit |
| Preço cai -40% | Stop loss |
| Minuto 70+ | Sell forçado |
| Partida encerrada | Liquidação final |

---

## ⚠️ Riscos e Limitações

### Técnicos
- **Gas fees Polygon**: Cada ordem custa ~$0.01-0.05 (baixo, mas soma)
- **Liquidez**: Mercados esportivos da Polymarket têm liquidez variável
- **Latência**: Eventos ao vivo têm delay de alguns segundos
- **API limits**: Sportradar trial tem limite de requisições

### Financeiros
- Sempre comece em **simulation_mode=True** para testar
- Nunca coloque mais do que pode perder
- O bot não garante lucro — é uma ferramenta automatizada

### Regulatórios
- Verifique as leis de apostas na sua jurisdição
- Polymarket pode ter restrições por região

---

## 🔧 Personalização

### Mudar estratégia de saída
```python
# Em BotConfig:
sell_on_favorable_goal = True   # Vender quando time apostado faz gol
sell_on_adverse_goal = True     # Vender quando adversário faz gol
profit_target_pct = 0.30        # +30% take profit
stop_loss_pct = 0.40            # -40% stop loss
sell_after_minutes = 70         # Minuto de saída forçada
```

### Adicionar mais ligas
```python
# Em FootballDataClient.get_upcoming_matches():
# Mudar "soccer_epl" para:
# soccer_brazil_campeonato  → Brasileirão
# soccer_spain_la_liga      → La Liga
# soccer_uefa_champs_league → Champions League
# soccer_italy_serie_a      → Serie A
```

---

## 📞 APIs necessárias

| API | Uso | Custo |
|---|---|---|
| [The Odds API](https://the-odds-api.com) | Odds pré-jogo | Grátis (500 req/mês) |
| [Sportradar](https://sportradar.com) | Placar ao vivo | Trial grátis |
| [Polymarket CLOB](https://docs.polymarket.com) | Execução de ordens | Grátis |
| Polygon RPC | Transações blockchain | Grátis |
