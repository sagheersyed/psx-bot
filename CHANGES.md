# Purani files mein jo masle mile aur v2 mein kaise hal hue

| # | Masla (purana code) | Asar | v2 fix |
|---|---|---|---|
| 1 | `cli_runner.py` `format_whatsapp_message` import karta tha jo `psx_analyzer.py` mein exist hi nahi | WhatsApp par har analysis fail | `psx/formatter.py` |
| 2 | `smc_engine`: `volume[-1]` aaj ki **adhoori** candle ka tha, 20-day average se compare | Din ke beech hamesha "volume dry-up / institutional absorption" ka jhoota signal | Sirf mukammal candles, aakhri 3 bars ka average |
| 3 | OTE fib "last swing high" aur "last swing low" se, chahe low high ke baad aaye | Fib levels ulte/ghalat | Sahi bullish leg (low → uske baad ka high); leg toot jaye to invalid |
| 4 | Verdict if/elif cascade, "first match wins" | Ek condition baqi sab ignore | Score-based: har factor vote deta hai |
| 5 | 6 timeframes barabar (1M = 1D) | 1M ka shor daily trend barabar | Weighted (1D 35%, 60M 25% ... 1M 5%) |
| 6 | EMA200 sirf 60 bars hon to bhi "EMA200" nikalta (window ghata kar) | Fake EMA200 | <200 bars par EMA200 use nahi hota |
| 7 | Timestamps UTC mein, PKT mein convert nahi | Intraday candles ghalat waqt par | Asia/Karachi conversion |
| 8 | "Lower circuit" check mein `abs(open-close)<0.25` | Koi bhi flat candle circuit lagti | Circuit % config (`PSX_CIRCUIT_PCT`) se |
| 9 | Dashboard: "AVOID / DO NOT BUY" mein "BUY" hai → green dikhta tha | Khatarnak signal green | JS check AVOID pehle |
| 10 | Dashboard `smc.liquidity_sweeps` mangta tha, engine deta nahi tha | Sweep card hamesha khali | Liquidity sweep detection |
| 11 | `stop_bot.bat` har `node.exe` kill karta tha | Doosri Node apps bhi band | PID file se sirf bot |
| 12 | `D:\bot` hardcoded | Folder badla to sab toota | `%~dp0` relative paths |
| 13 | Har reconnect par naya socket, purane listeners zinda | Duplicate replies | Purana socket close + single reconnect timer |
| 14 | Python process par timeout nahi, parallel requests | Bot atak sakta tha | 90s timeout + queue + 15s cooldown |
| 15 | Dashboard `host=0.0.0.0` | Wi-Fi par sab ko khula | Default 127.0.0.1 |
| 16 | Koi cache nahi | Har message par 8+ network calls | TTL cache + retry |
| 17 | Backtest/accuracy tracking nahi | Pata hi nahi bot kitna sahi hai | backtest.py + journal.py |
