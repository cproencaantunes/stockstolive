# Trading Agent — Covered Call & Bear Call Spread

Agente autónomo para gestão de covered calls e bear call spreads
em ações tech americanas via Interactive Brokers.

## Stack

| Componente | Fase 1 (gratuito) | Fase 2 (produção) |
|---|---|---|
| LLM | Gemini 2.0 Flash | Claude Sonnet / Opus |
| Servidor | Railway free ($0) | Railway Hobby ($5/mês) |
| Broker | IBKR paper trading | IBKR conta real |
| Notificações | Email + Pushover | Igual |

---

## Estrutura

```
trading-agent/
├── agent_manager.py      ← orquestrador principal
├── analysis.py           ← decisões de estratégia via LLM
├── llm_client.py         ← interface única Gemini/Claude
├── options.py            ← chain de opções e execução IBKR
├── portfolio.py          ← estado e persistência
├── data.py               ← dados de mercado e indicadores
├── notifications.py      ← email e push notifications
├── config.py             ← configuração central
├── dashboard/
│   └── app.py            ← Flask API + dashboard
├── data/                 ← estado persistido (commitado)
├── logs/                 ← logs do agente
├── requirements.txt
├── railway.toml
├── start.sh
└── .env.example
```

---

## Deploy no Railway (10 minutos)

### 1. Fork/clone este repositório

```bash
git clone https://github.com/SEU_USER/trading-agent
cd trading-agent
```

### 2. Criar conta Railway

- Aceder a [railway.com](https://railway.com)
- Criar conta → ligar ao GitHub
- Clicar "New Project" → "Deploy from GitHub repo"
- Selecionar este repositório

### 3. Configurar variáveis de ambiente

No Railway → Settings → Variables, adicionar:

```
LLM_PROVIDER     = gemini
LLM_MODEL        = gemini-2.0-flash
GEMINI_API_KEY   = AIza...          ← da Google AI Studio
IBKR_TRADING_MODE = paper
```

Opcional (notificações):
```
EMAIL_FROM       = o_teu@gmail.com
EMAIL_TO         = o_teu@gmail.com
EMAIL_PASSWORD   = app_password_do_gmail
PUSHOVER_APP     = token_pushover
PUSHOVER_USER    = chave_pushover
```

### 4. Deploy automático

O Railway deteta o `railway.toml` e faz deploy automaticamente.
Em ~2 minutos o agente está a correr.

---

## Migrar de Gemini → Claude

No Railway → Variables, mudar apenas:

```
LLM_PROVIDER      = claude              (era gemini)
LLM_MODEL         = claude-sonnet-4-6  (era gemini-2.0-flash)
ANTHROPIC_API_KEY = sk-ant-...          (nova variável)
```

O Railway reinicia em 30 segundos. **Zero alterações no código.**

---

## Migrar de paper trading → real

No Railway → Variables:

```
IBKR_TRADING_MODE = live    (era paper)
IBKR_PORT         = 4001    (era 7497)
```

---

## Portfolio — adicionar/remover ações

Via dashboard (botão "Adicionar ação") ou via API:

```bash
# Adicionar
curl -X POST https://SEU-DOMINIO.railway.app/api/portfolio/add \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "shares": 100, "target_otm_pct": 0.02}'

# Remover (posição atual expira normalmente)
curl -X POST https://SEU-DOMINIO.railway.app/api/portfolio/remove \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'
```

---

## Scheduler

| Tarefa | Quando |
|---|---|
| Roll semanal | Sexta 15h30 ET |
| Monitor posições | Terça-Quinta 10h-15h (hora a hora) |
| Research após fecho | Todos os dias úteis 18h00 ET |
| Briefing pré-abertura | Terça-Sábado 08h30 ET |

---

## Desenvolvimento local

```bash
pip install -r requirements.txt

# Copiar e preencher variáveis
cp .env.example .env

# Correr só o dashboard (sem IBKR)
python dashboard/app.py

# Correr agente completo (precisa de IBKR TWS/Gateway)
python agent_manager.py
```

---

## Notas de segurança

- **Nunca commitar** ficheiros `.env` ou credenciais
- API keys vivem **exclusivamente** em variáveis de ambiente
- O `data/portfolio.json` é commitado intencionalmente (estado, sem credenciais)
- Criar API key IBKR **sem permissão de transferências**
