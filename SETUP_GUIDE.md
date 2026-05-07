# Signal Engine — Setup Guide
## How to run the full NSE+BSE+F&O signal tester on your laptop

---

## Step 1 — Install Python
Download Python 3.10 or above from https://python.org
During install, tick "Add Python to PATH"

---

## Step 2 — Create your Telegram bot
1. Open Telegram → search @BotFather
2. Send /newbot
3. Name it: StockSignalTest
4. Username: StockSignalTestBot (must end in bot)
5. Copy the token it gives you (looks like 7284910:AAF_xK9m...)

Get your Chat ID:
1. Search @userinfobot on Telegram
2. Send any message
3. It replies with your Chat ID number — copy it

---

## Step 3 — Edit signal_engine.py
Open signal_engine.py in any text editor.
Find these two lines near the top and fill them in:

    TELEGRAM_BOT_TOKEN = "paste your token here"
    TELEGRAM_CHAT_ID   = "paste your chat id here"

Save the file.

---

## Step 4 — Install dependencies
Open Terminal (Mac/Linux) or Command Prompt (Windows).
Navigate to this folder:

    cd path/to/stock_signal_tester

Install all libraries:

    pip install -r requirements.txt

---

## Step 5 — Run the engine

    python signal_engine.py

You will see it start in the terminal.
You will receive a startup message on Telegram immediately.
At 9:00 AM it scans all NSE+BSE stocks automatically.
Every 30 minutes it sends signals to your Telegram.
At 4:00 PM it sends the daily summary.

---

## Step 6 — Track results in Google Sheets
1. Open Google Sheets → create a new sheet
2. Import signals_log.csv weekly (File → Import)
3. Add a Results column — update each signal as:
   - Target Hit
   - Stop Loss Hit
   - Still Open
4. Calculate accuracy = Target Hit / Total Signals × 100

---

## What signals look like on Telegram

BUY signal:
    🟢 BUY SIGNAL — HDFCBANK (NSE)
    Entry price: ₹1,642
    Target:      ₹1,740
    Stop loss:   ₹1,598
    Confidence:  82%
    Reason: MACD bullish crossover + Volume spike

F&O signal:
    🟢 F&O SIGNAL — HDFCBANK 1650 CE
    Expiry:       03 Apr
    Buy premium: ₹48.5
    Target prem: ₹77.6
    SL premium:  ₹24.2
    Confidence:  79%

---

## Common issues

"Module not found" error:
    pip install yfinance pandas pandas-ta requests schedule nsepython

"Telegram message not sending":
    Check your bot token and chat ID are correct
    Make sure you clicked Start on your bot in Telegram

"No signals generated":
    Market might be closed (runs only 9:15 AM - 3:30 PM)
    Wait for morning scan to complete first (takes 10-15 min)

NSEpython error:
    pip install nsepython --upgrade
    The script uses a fallback list of 100 stocks if NSEpython fails

---

## Running on Google Colab (no laptop needed)
1. Go to colab.research.google.com
2. Upload signal_engine.py
3. Run: !pip install -r requirements.txt
4. Run the script
5. Keep the tab open — Colab runs as long as tab is open

---

## Important
This script is for testing and educational purposes only.
Signals generated are not financial advice.
Always verify signals before making any real trades.
Past signal accuracy does not guarantee future results.
