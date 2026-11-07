# 🇵🇰 PSX Smart Bot v2

```
psx_bot/
├── config.py            # saari settings (circuit %, timeframe weights, thresholds)
├── .env.example         # copy karke .env banayein
├── psx/                 # ← asal engine (Python package)
│   ├── data.py          #   SCSTrade / PSX DPS / Yahoo — cache + retry + Karachi timezone
│   ├── indicators.py    #   EMA, RSI, ATR, CMF, OBV, MACD (pure pandas)
│   ├── smc.py           #   Swings, FVG, Order Block, Liquidity Sweep, BOS/CHoCH, OTE
│   ├── mtf.py           #   6 timeframes, weighted alignment
│   ├── scoring.py       #   factor scores, confidence, entry/stop/targets, verdict
│   ├── signal.py        #   ek hi jagah jahan signal banta hai (live + backtest dono)
│   ├── backtest.py      #   walk-forward backtest + trade simulator
│   ├── journal.py       #   har signal SQLite mein save → baad mein asal result match
│   ├── analyzer.py      #   orchestrator (dashboard/bot isi ko call karte hain)
│   ├── formatter.py     #   WhatsApp message
│   └── charts.py
├── web/                 # Flask dashboard (app.py + templates/index.html)
├── bot/                 # WhatsApp bot (whatsapp_bot.js)
├── scripts/             # cli_runner, run_backtest, evaluate_journal
├── launchers/           # double-click .bat/.vbs files
├── tests/               # python -m tests.test_engine ; python -m tests.test_pipeline
└── data/                # charts, journal.db, bot.pid, bot.log
```

## Setup
```powershell
pip install -r requirements.txt
copy .env.example .env
cd bot && npm install && cd ..
```
Purana WhatsApp login bachana ho to purana `auth_session` folder `bot\` mein copy kar dein (QR dobara scan nahi karna parega).

## Chalana
| Kaam | File |
|---|---|
| Dashboard | `launchers\Start_Dashboard.bat` |
| Bot (window) | `launchers\Start_Bot.bat` |
| Bot (background) | `launchers\Start_Bot_Background.vbs` |
| Bot band / status | `launchers\Stop_Bot.bat` / `Bot_Status.bat` |
| Roz ke signals ka natija | `launchers\Daily_Evaluate.bat` |

WhatsApp par: ticker (`OGDC`), `stats` (bot ka live record), `help`.

## Prediction behtar kaise hoti hai (zaroor parhein)
1. **Backtest chalayein** — `python scripts\run_backtest.py OGDC SYS LUCK ENGRO HUBC PAEL TRG`.
   Result DB mein save hota hai; jis stock par strategy historically negative expectancy deti hai wahan bot confidence khud kam kar deta hai.
2. **Journal** — har BUY/WATCH signal auto-save hota hai. `Daily_Evaluate.bat` roz chalayein; 1-2 mahine baad `stats` se asal win-rate dikhega.
3. **Weights tune karein** — `psx/scoring.py` ke `WEIGHTS` aur `config.py` ke thresholds backtest dekh kar badlein, andaze se nahi.
4. **Confidence ≠ probability.** Ye "signal kitna saaf aur mutafiq hai" ka score hai. Asal hit-rate sirf backtest/journal batate hain.

## Zaroori note
Ye analysis tool hai, guarantee nahi. PSX par circuit limits, thin liquidity aur news gaps hote hain; position size ko stop-loss se tay karein.
