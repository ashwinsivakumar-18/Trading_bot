"""
=============================================================
  STOCK SIGNAL TESTING ENGINE
  Tests all NSE + BSE stocks + F&O signals
  Sends alerts to Telegram + logs to CSV
=============================================================

SETUP INSTRUCTIONS:
1. Install dependencies:
   pip install yfinance pandas pandas-ta requests nsepython schedule

2. Fill in your credentials below (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

3. Run:
   python signal_engine.py

=============================================================
"""

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import schedule
import time
import csv
import os
import json
from datetime import datetime, date
import pytz
from nsepython import nse_eq_symbols, fnolist
india = pytz.timezone("Asia/Kolkata")
# ─────────────────────────────────────────────
#  YOUR CREDENTIALS — FILL THESE IN
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8604631232:AAGspXA0tCSlfDMwTRhAK86iHpBeF2H4PnE"   # From BotFather
TELEGRAM_CHAT_ID   = "2121122097"     # From @userinfobot

# ─────────────────────────────────────────────
#  SIGNAL SETTINGS — TUNE THESE LATER
# ─────────────────────────────────────────────
MIN_VOLUME           = 1500000   # Swing: higher volume = liquid stocks only
MIN_PRICE            = 250       # Swing: no penny stocks below ₹50
MIN_PRICE_PREFERRED  = 300      # Preferred minimum for cleaner signals
RSI_OVERSOLD         = 45       # Swing: slightly higher threshold
RSI_OVERBOUGHT       = 62       # Swing: slightly lower threshold
CONFIDENCE_THRESHOLD = 65       # Swing: higher bar for quality signals
SWING_HOLD_DAYS      = "3-7"    # Expected hold time for swing trades
ATR_PERIOD           = 14       # ATR period for target calculation
ATR_TARGET_MULT      = 3.0      # Target = entry + ATR * 3 (bigger targets)
ATR_SL_MULT          = 1.5      # Stop loss = entry - ATR * 1.5
LOG_FILE            = "signals_log.csv"
WATCHLIST_FILE      = "daily_watchlist.json"
POSITIONS_FILE      = "open_positions.json"  # Tracks all active signals

# ─────────────────────────────────────────────
#  TELEGRAM SENDER
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  NSE / BSE OFFICIAL HOLIDAY CALENDAR
#  Saturdays and Sundays are blocked automatically
#  via weekday check — no need to list them here.
#  Update NSE_HOLIDAYS every January with new year list.
# ─────────────────────────────────────────────

# Each entry: "DD-MM-YYYY": "Holiday Name"
NSE_HOLIDAYS = {

    # ══════════════════════════════
    #  2025 NSE OFFICIAL HOLIDAYS
    # ══════════════════════════════
    "26-01-2025": "Republic Day",
    "26-02-2025": "Mahashivratri",
    "14-03-2025": "Holi",
    "31-03-2025": "Id-Ul-Fitr (Eid)",
    "10-04-2025": "Shri Ram Navami",
    "14-04-2025": "Dr. Baba Saheb Ambedkar Jayanti",
    "18-04-2025": "Good Friday",
    "01-05-2025": "Maharashtra Day",
    "15-08-2025": "Independence Day",
    "27-08-2025": "Ganesh Chaturthi",
    "02-10-2025": "Mahatma Gandhi Jayanti",
    "02-10-2025": "Dussehra",
    "21-10-2025": "Diwali Laxmi Pujan",
    "22-10-2025": "Diwali Balipratipada",
    "05-11-2025": "Prakash Gurpurb Sri Guru Nanak Dev Ji",
    "25-12-2025": "Christmas",

    # ══════════════════════════════
    #  2026 NSE OFFICIAL HOLIDAYS
    #  Source: NSE India confirmed list
    # ══════════════════════════════
    "15-01-2026": "Municipal Corporation Election - Maharashtra",
    "26-01-2026": "Republic Day",
    "03-03-2026": "Holi",
    "26-03-2026": "Shri Ram Navami",
    "31-03-2026": "Shri Mahavir Jayanti",
    "03-04-2026": "Good Friday",
    "14-04-2026": "Dr. Baba Saheb Ambedkar Jayanti",
    "01-05-2026": "Maharashtra Day",
    "28-05-2026": "Bakri Id",
    "26-06-2026": "Muharram",
    "14-09-2026": "Ganesh Chaturthi",
    "02-10-2026": "Mahatma Gandhi Jayanti",
    "20-10-2026": "Dussehra",
    "10-11-2026": "Diwali Balipratipada",
    "24-11-2026": "Prakash Gurpurb Sri Guru Nanak Dev Ji",
    "25-12-2026": "Christmas",

}


def get_next_trading_day() -> str:
    """
    Calculate and return the next trading day after today.
    Skips weekends and all listed NSE/BSE holidays.
    Returns date string like 'Monday, 06 Apr 2026'
    """
    check = datetime.now(india) + pd.Timedelta(days=1)
    for _ in range(30):
        weekday   = check.weekday()
        check_str = check.strftime("%d-%m-%Y")
        if weekday < 5 and check_str not in NSE_HOLIDAYS:
            return check.strftime("%A, %d %b %Y")
        check += pd.Timedelta(days=1)
    return "next trading day"


def is_market_holiday() -> bool:
    """
    Return True if today is a declared NSE/BSE market holiday
    OR a Saturday or Sunday.
    Saturdays and Sundays are always blocked regardless of the holiday list.
    """
    now       = datetime.now(india)
    weekday   = now.weekday()   # 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun

    # Weekend — always blocked
    if weekday >= 5:
        return True

    # Check declared holiday list
    today_str = now.strftime("%d-%m-%Y")
    return today_str in NSE_HOLIDAYS


def is_market_open() -> bool:
    """
    Return True only if:
      1. Today is NOT a holiday or weekend
      2. Current time is within NSE market hours (9:15 AM - 3:30 PM)
    """
    if is_market_holiday():
        return False
    now   = datetime.now(india)
    h, m  = now.hour, now.minute
    after  = (h > 9) or (h == 9 and m >= 15)
    before = (h < 15) or (h == 15 and m <= 30)
    return after and before


def get_holiday_name() -> str:
    """
    Return the holiday name for today.
    Returns 'Saturday' or 'Sunday' for weekends.
    Returns empty string if today is a normal trading day.
    """
    now       = datetime.now(india)
    weekday   = now.weekday()
    today_str = now.strftime("%d-%m-%Y")

    if weekday == 5:
        return "Saturday"
    if weekday == 6:
        return "Sunday"
    return NSE_HOLIDAYS.get(today_str, "")



# ─────────────────────────────────────────────
#  INTERNET + TELEGRAM RETRY SYSTEM
# ─────────────────────────────────────────────

_pending_messages     = []      # Messages queued during outage
_last_internet_status = True    # Assume connected at start

# Tracks which stocks already got a signal today — resets every morning
# Format: {"SYMBOL_SIGNALTYPE"} e.g. {"AARTIIND_BUY", "BHARATFORG_BUY"}
_signals_sent_today   = set()


def is_internet_available() -> bool:
    """Ping Telegram servers to check internet. Returns True/False."""
    try:
        r = requests.get("https://api.telegram.org", timeout=5)
        return r.status_code < 500
    except Exception:
        return False


def _send_raw(message: str) -> bool:
    """Send one Telegram message. Returns True on success."""
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def send_telegram(message: str):
    """
    Send Telegram message with retry.
    Tries 3 times (5s apart). If all fail — queues message.
    Queued messages auto-send when internet returns.
    """
    global _pending_messages
    for attempt in range(1, 4):
        if _send_raw(message):
            print(f"[Telegram] Sent: {message[:60]}...")
            return
        if attempt < 3:
            print(f"[Telegram] Attempt {attempt} failed — retry in 5s...")
            time.sleep(5)
    _pending_messages.append(message)
    print(f"[Telegram] Queued — no internet. Queue: {len(_pending_messages)}")


def send_pending_messages():
    """Resend all queued messages after internet restores."""
    global _pending_messages
    if not _pending_messages:
        return
    print(f"[Reconnect] Flushing {len(_pending_messages)} queued message(s)...")
    still_pending = []
    for msg in _pending_messages:
        if _send_raw(msg):
            time.sleep(0.5)
        else:
            still_pending.append(msg)
    _pending_messages = still_pending
    if not still_pending:
        print("[Reconnect] All queued messages delivered.")
    else:
        print(f"[Reconnect] {len(still_pending)} still pending.")


def check_internet_and_flush():
    """
    Called every 60 seconds in main loop.
    Detects internet drop and restoration.
    Auto-sends queued messages on reconnection.
    """
    global _last_internet_status
    current = is_internet_available()

    if not current and _last_internet_status:
        # Just lost internet
        _last_internet_status = False
        print(f"\n[{datetime.now(india).strftime('%H:%M:%S')}] "
              f"WARNING: Internet lost — signals will be queued.")

    elif current and not _last_internet_status:
        # Just regained internet
        _last_internet_status = True
        print(f"\n[{datetime.now(india).strftime('%H:%M:%S')}] "
              f"Internet restored!")
        note = (
            f"✅ <b>Connection Restored</b>\n\n"
            f"⏰ {datetime.now(india).strftime('%d %b %Y at %I:%M %p')}\n"
            f"Signal engine back online.\n"
        )
        if _pending_messages:
            note += f"📨 Sending {len(_pending_messages)} queued signal(s) now..."
        _send_raw(note)
        send_pending_messages()


# ─────────────────────────────────────────────
#  HEARTBEAT — SENT EVERY 1 HOUR
#  Confirms engine is alive and connected.
#  Silently skipped if internet is down.
# ─────────────────────────────────────────────

_heartbeat_count = 0   # Increments each hour — shows total uptime


def send_heartbeat():
    """
    Sends a concise 'engine alive' ping to Telegram every 1 hour.
    Includes:
      - Current IST time
      - Market status (open / closed / holiday)
      - Pending queued messages (if any)
      - Uptime counter (hours since engine started)
    Skipped silently if internet is unavailable.
    """
    global _heartbeat_count
    _heartbeat_count += 1

    if not is_internet_available():
        print(f"[Heartbeat #{_heartbeat_count}] Skipped — no internet.")
        return

    now        = datetime.now(india)                          # Always IST
    time_str   = now.strftime("%d %b %Y  %I:%M %p IST")      # e.g. 07 May 2026  11:00 AM IST
    pending    = len(_pending_messages)

    # Market status line
    if is_market_holiday():
        holiday_name = get_holiday_name()
        market_line  = f"🏖️ Market closed — {holiday_name}"
    elif is_market_open():
        market_line  = "🟢 Market OPEN"
    else:
        market_line  = "🔴 Market closed (after hours)"

    # Engine always runs 24x7 — clarify state when market is shut
    if is_market_open():
        engine_line = "✅ Engine connected &amp; scanning"
    else:
        engine_line = "✅ Engine connected &amp; waiting for market open"

    # Pending queue line (only shown when non-zero)
    queue_line = (
        f"\n📨 {pending} message(s) queued (will retry when online)"
        if pending > 0 else ""
    )

    msg = (
        f"💓 <b>Heartbeat #{_heartbeat_count}</b>\n\n"
        f"⏰ {time_str}\n"
        f"{market_line}\n"
        f"{engine_line}{queue_line}\n\n"
        f"⏱️ Uptime: ~{_heartbeat_count} hr(s)"
    )

    if _send_raw(msg):
        print(f"[Heartbeat #{_heartbeat_count}] Sent at {now.strftime('%H:%M')}.")
    else:
        print(f"[Heartbeat #{_heartbeat_count}] Failed to send.")


def send_startup_message():
    holiday      = get_holiday_name()
    is_holiday   = is_market_holiday()

    # Detect today's expiry indices (only relevant on trading days)
    expiry_today = [] if is_holiday else [
        cfg["display"]
        for sym, cfg in INDEX_CONFIG.items()
        if datetime.now(india).weekday() == cfg["expiry_weekday"]
    ]
    expiry_line = (
        f"\n🔔 <b>Expiry today:</b> {', '.join(expiry_today)}"
        if expiry_today else ""
    )

    if is_holiday:
        next_day = get_next_trading_day()
        msg = (
            "🚀 <b>Signal Engine Started</b>\n\n"
            f"📅 {datetime.now(india).strftime('%d %b %Y')}  "
            f"⏰ {datetime.now(india).strftime('%I:%M %p')}\n\n"
            f"🏖️ <b>Today is a market holiday — {holiday}</b>\n"
            "NSE and BSE are closed today.\n"
            "Engine is running but no signals will be sent.\n\n"
            f"📅 <b>Next trading day: {next_day}</b>\n"
            "Scans resume automatically at 9:00 AM.\n\n"
            "⚠️ For testing and educational use only."
        )
    else:
        msg = (
            "🚀 <b>Signal Engine Started</b>\n\n"
            f"📅 {datetime.now(india).strftime('%d %b %Y')}  "
            f"⏰ {datetime.now(india).strftime('%I:%M %p')}"
            f"{expiry_line}\n\n"
            "<b>Stock signals</b>\n"
            "  09:00 AM  — Morning scan (all NSE+BSE)\n"
            "  Every 30m — Intraday stock scan\n"
            "  04:00 PM  — Stock summary\n\n"
            "<b>Index F&O signals</b>\n"
            "  09:00 AM  — Pre-market scan\n"
            "  Every 15m — Live index scan\n"
            "  Every 5m  — Expiry crunch (1–3:15 PM)\n"
            "  03:35 PM  — Index summary\n\n"
            "<b>Indices covered</b>\n"
            "  🔷 NIFTY 50     — Thu expiry\n"
            "  🔷 BANK NIFTY   — Wed expiry\n"
            "  🔷 SENSEX       — Fri expiry\n"
            "  🔷 FIN NIFTY    — Tue expiry\n"
            "  🔷 MIDCAP NIFTY — Mon expiry\n\n"
            "All signals logged to signals_log.csv\n"
            "💓 Heartbeat ping every 1 hour\n"
            "⚠️ For testing and educational use only."
        )
    send_telegram(msg)


# ─────────────────────────────────────────────
#  CSV LOGGER
# ─────────────────────────────────────────────
def log_signal(data: dict):
    """
    Append a signal to the CSV log file.
    Uses extrasaction='ignore' so any extra fields in the dict
    are silently ignored — no more fieldnames errors.
    """
    file_exists = os.path.isfile(LOG_FILE)
    fieldnames  = [
        "date", "time", "stock", "exchange", "signal_type",
        "entry_price", "target", "stop_loss", "confidence",
        "rsi", "gain_pct", "sl_pct", "hold_days", "atr",
        "macd_cross", "volume_spike", "reason", "status",
        # Index F&O extra fields
        "vix_level", "vix_current", "sr_pivot",
        "fo_strike", "fo_option_type", "fo_expiry",
        "fo_premium", "fo_tgt_premium", "fo_sl_premium",
        "signal_category",
    ]
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore"   # silently ignore unknown fields
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)
    print(f"[LOG] Signal logged: {data['stock']} "
          f"{data['signal_type']} {data['confidence']}%")


# ─────────────────────────────────────────────
#  POSITION MONITORING
#  Tracks every signal sent and alerts when
#  target is hit or stop loss is breached
# ─────────────────────────────────────────────

def load_open_positions() -> list:
    """
    Load all currently open positions from file.
    Sanitises any None date/time fields that cause format errors.
    """
    if not os.path.isfile(POSITIONS_FILE):
        return []
    try:
        with open(POSITIONS_FILE, "r") as f:
            positions = json.load(f)
        # Sanitise — fill None date/time with safe defaults
        today_str = date.today().strftime("%d-%m-%Y")
        now_str   = datetime.now(india).strftime("%H:%M")
        for pos in positions:
            if not pos.get("signal_date"):
                pos["signal_date"] = today_str
            if not pos.get("signal_time"):
                pos["signal_time"] = now_str
            if not pos.get("exchange"):
                pos["exchange"] = "NSE"
            if not pos.get("category"):
                pos["category"] = "STOCK"
        return positions
    except Exception:
        return []


def save_open_positions(positions: list):
    """Save open positions back to file."""
    try:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(positions, f, indent=2)
    except Exception as e:
        print(f"[Positions] Save error: {e}")


def add_open_position(sig: dict):
    """
    Add a newly sent signal to the open positions tracker.
    Called every time a BUY or SELL signal is sent.
    """
    positions = load_open_positions()

    # Avoid duplicate entries for same stock
    positions = [
        p for p in positions
        if not (p["stock"] == sig["stock"] and
                p["exchange"] == sig.get("exchange", "NSE"))
    ]

    position = {
        "stock":        sig["stock"],
        "exchange":     sig.get("exchange", "NSE"),
        "symbol":       sig["stock"] + "." + ("NS" if sig.get("exchange","NSE") == "NSE" else "BO"),
        "signal_type":  sig["signal_type"],
        "entry_price":  sig["entry_price"],
        "target":       sig["target"],
        "stop_loss":    sig["stop_loss"],
        "confidence":   sig["confidence"],
        "signal_date":  sig.get("date") or date.today().strftime("%d-%m-%Y"),
        "signal_time":  sig.get("time") or datetime.now(india).strftime("%H:%M"),
        "reason":       sig.get("reason", ""),
        "category":     sig.get("signal_category", "STOCK"),
        # For index F&O positions
        "fo_strike":        sig.get("fo_strike"),
        "fo_option_type":   sig.get("fo_option_type"),
        "fo_expiry":        sig.get("fo_expiry"),
        "fo_premium":       sig.get("fo_premium"),
        "fo_tgt_premium":   sig.get("fo_tgt_premium"),
        "fo_sl_premium":    sig.get("fo_sl_premium"),
        "index_price":      sig.get("index_price"),
    }
    positions.append(position)
    save_open_positions(positions)
    print(f"[Positions] Added: {sig['stock']} {sig['signal_type']} "
          f"entry:{sig['entry_price']} target:{sig['target']} sl:{sig['stop_loss']}")


def format_target_hit_message(pos: dict, current_price: float) -> str:
    """Format Telegram message when target is hit."""
    entry      = pos["entry_price"]
    target     = pos["target"]
    sig_date   = pos.get("signal_date") or "N/A"
    sig_time   = pos.get("signal_time") or "N/A"
    gain       = round(((current_price - entry) / entry) * 100, 2) if pos["signal_type"] == "BUY" \
                 else round(((entry - current_price) / entry) * 100, 2)
    return (
        f"🎯 <b>TARGET HIT — {pos['stock']} ({pos['exchange']})</b>\n\n"
        f"✅ <b>BOOK PROFIT NOW</b>\n\n"
        f"📈 Entry price:    ₹{entry}\n"
        f"🎯 Target:         ₹{target}\n"
        f"💰 Current price:  ₹{current_price}\n"
        f"📊 Gain:           +{gain}%\n\n"
        f"📅 Signal sent:    {sig_date} at {sig_time}\n"
        f"⏰ Target hit:     {datetime.now(india).strftime('%d %b %Y at %I:%M %p')}\n\n"
        f"💡 <b>Action: Sell your position and book profit.</b>\n"
        f"⚠️ For educational purposes only."
    )


def format_stoploss_hit_message(pos: dict, current_price: float) -> str:
    """Format Telegram message when stop loss is hit."""
    entry    = pos["entry_price"]
    sl       = pos["stop_loss"]
    sig_date = pos.get("signal_date") or "N/A"
    sig_time = pos.get("signal_time") or "N/A"
    loss     = round(((entry - current_price) / entry) * 100, 2) if pos["signal_type"] == "BUY" \
               else round(((current_price - entry) / entry) * 100, 2)
    return (
        f"🛑 <b>STOP LOSS HIT — {pos['stock']} ({pos['exchange']})</b>\n\n"
        f"❌ <b>EXIT POSITION NOW</b>\n\n"
        f"📈 Entry price:    ₹{entry}\n"
        f"🛑 Stop loss:      ₹{sl}\n"
        f"💰 Current price:  ₹{current_price}\n"
        f"📊 Loss:           -{loss}%\n\n"
        f"📅 Signal sent:    {sig_date} at {sig_time}\n"
        f"⏰ SL hit:         {datetime.now(india).strftime('%d %b %Y at %I:%M %p')}\n\n"
        f"💡 <b>Action: Exit immediately to protect capital.</b>\n"
        f"⚠️ Stop losses exist to protect your capital. Always respect them."
    )


def format_fo_target_hit_message(pos: dict, current_price: float) -> str:
    """Format Telegram message when F&O index target is hit."""
    entry_idx = float(pos.get("index_price") or pos.get("entry_price") or 0)
    tgt_idx   = float(pos.get("target") or 0)
    premium   = float(pos.get("fo_premium") or 0)
    tgt_prem  = float(pos.get("fo_tgt_premium") or 0)
    gain_pct  = round(((tgt_prem - premium) / premium) * 100, 1) if premium > 0 else 0
    entry_str = f"{entry_idx:,.0f}" if entry_idx else "N/A"
    tgt_str   = f"{tgt_idx:,}"     if tgt_idx   else "N/A"
    return (
        f"🎯 <b>INDEX F&O TARGET HIT — "
        f"{pos['stock']} {pos.get('fo_strike','')} "
        f"{pos.get('fo_option_type','')}</b>\n\n"
        f"✅ <b>BOOK PROFIT NOW</b>\n\n"
        f"📊 Index entry:    {entry_str}\n"
        f"🎯 Index target:   {tgt_str}\n"
        f"💰 Current index:  {current_price:,.0f}\n\n"
        f"📈 Premium bought: ₹{premium}\n"
        f"🎯 Target premium: ₹{tgt_prem}  (+{gain_pct}%)\n"
        f"📅 Expiry:         {pos.get('fo_expiry', 'N/A')}\n\n"
        f"⏰ Target hit: {datetime.now(india).strftime('%d %b %Y at %I:%M %p')}\n\n"
        f"💡 <b>Action: Square off your options position.</b>\n"
        f"⚠️ For educational purposes only."
    )


def update_log_status(stock: str, signal_date: str,
                      signal_time: str, new_status: str):
    """Update the status column in signals_log.csv for a closed position."""
    if not os.path.isfile(LOG_FILE):
        return
    # Encoding fallback
    df = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(LOG_FILE, encoding=enc)
            break
        except Exception:
            continue
    if df is None:
        return
    try:
        mask = (
            (df["stock"] == stock) &
            (df["date"]  == signal_date) &
            (df["time"]  == signal_time)
        )
        df.loc[mask, "status"] = new_status
        df.to_csv(LOG_FILE, index=False)
    except Exception as e:
        print(f"[Log] Status update error: {e}")


def monitor_open_positions():
    """
    Core position monitoring function.
    Runs every 15 minutes alongside the intraday scan.
    Checks every open position against current price.
    Sends TARGET HIT or STOP LOSS HIT alert immediately.
    """
    positions = load_open_positions()
    if not positions:
        print("[Monitor] No open positions to monitor.")
        return

    print(f"\n[Monitor] Checking {len(positions)} open position(s)...")
    still_open  = []
    closed_count = 0

    for pos in positions:
        symbol       = pos["symbol"]
        signal_type  = pos["signal_type"]
        entry        = float(pos["entry_price"])
        target       = float(pos["target"])
        stop_loss    = float(pos["stop_loss"])
        category     = pos.get("category", "STOCK")

        try:
            # Fetch latest price
            df = fetch_stock_data(symbol, period="2d", interval="5m")
            if df is None or df.empty:
                # Try daily fallback
                df = fetch_stock_data(symbol, period="5d", interval="1d")
            if df is None or df.empty:
                print(f"  [Monitor] Cannot fetch price for {symbol} — keeping open")
                still_open.append(pos)
                continue

            current_price = round(float(df["Close"].iloc[-1]), 2)
            print(f"  {pos['stock']} — entry:₹{entry} "
                  f"current:₹{current_price} "
                  f"target:₹{target} sl:₹{stop_loss}")

            hit_target = False
            hit_sl     = False

            if signal_type == "BUY":
                hit_target = current_price >= target
                hit_sl     = current_price <= stop_loss
            else:  # SELL signal — short position
                hit_target = current_price <= target
                hit_sl     = current_price >= stop_loss

            if hit_target:
                # ── TARGET HIT ──
                if category in ("INDEX_FO", "F&O"):
                    msg = format_fo_target_hit_message(pos, current_price)
                else:
                    msg = format_target_hit_message(pos, current_price)
                send_telegram(msg)
                update_log_status(
                    pos["stock"],
                    pos.get("signal_date") or "",
                    pos.get("signal_time") or "",
                    "Target Hit"
                )
                print(f"  [Monitor] TARGET HIT: {pos['stock']} @ ₹{current_price}")
                closed_count += 1
                # Do not add to still_open — position is closed

            elif hit_sl:
                # ── STOP LOSS HIT ──
                msg = format_stoploss_hit_message(pos, current_price)
                send_telegram(msg)
                update_log_status(
                    pos["stock"],
                    pos.get("signal_date") or "",
                    pos.get("signal_time") or "",
                    "Stop Loss Hit"
                )
                print(f"  [Monitor] STOP LOSS HIT: {pos['stock']} @ ₹{current_price}")
                closed_count += 1
                # Do not add to still_open — position is closed

            else:
                # Still open — keep monitoring
                still_open.append(pos)
                pct = round(((current_price - entry) / entry) * 100, 2)
                print(f"  [Monitor] Open: {pos['stock']} "
                      f"P&L: {'+' if pct >= 0 else ''}{pct}%")

            time.sleep(0.3)

        except Exception as e:
            import traceback
            print(f"  [Monitor] Error checking {symbol}: {e}")
            print(f"  [Monitor] Traceback: {traceback.format_exc()}")
            still_open.append(pos)  # Keep open on error

    # Save updated open positions
    save_open_positions(still_open)

    if closed_count > 0:
        print(f"[Monitor] {closed_count} position(s) closed. "
              f"{len(still_open)} still open.")
    else:
        print(f"[Monitor] All {len(still_open)} position(s) still open — "
              f"no targets or stop losses hit yet.")


# ─────────────────────────────────────────────
#  FETCH ALL NSE + BSE SYMBOLS
# ─────────────────────────────────────────────
def get_all_nse_symbols():
    """Get all NSE equity symbols using nsepython."""
    try:
        symbols = nse_eq_symbols()
        # Convert to yfinance format (append .NS)
        return [s.strip() + ".NS" for s in symbols if s.strip()]
    except Exception as e:
        print(f"[NSE] Could not fetch live list, using fallback: {e}")
        # Fallback — top 100 NSE stocks for testing
        fallback = [
            "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR",
            "SBIN","BHARTIARTL","ITC","KOTAKBANK","LT","AXISBANK",
            "ASIANPAINT","MARUTI","TITAN","BAJFINANCE","WIPRO","HCLTECH",
            "SUNPHARMA","ULTRACEMCO","NESTLEIND","POWERGRID","NTPC",
            "TATAMOTORS","TATASTEEL","JSWSTEEL","HINDALCO","ADANIENT",
            "ADANIPORTS","BAJAJFINSV","TECHM","DIVISLAB","DRREDDY",
            "CIPLA","APOLLOHOSP","EICHERMOT","HEROMOTOCO","BAJAJ-AUTO",
            "ONGC","COALINDIA","BRITANNIA","GRASIM","INDUSINDBK",
            "SBILIFE","HDFCLIFE","BPCL","IOC","TATACONSUM","PIDILITIND",
            "HAVELLS","DABUR","MARICO","COLPAL","GODREJCP","BERGEPAINT",
            "ALKEM","TORNTPHARM","LUPIN","BIOCON","AUROPHARMA",
            "MUTHOOTFIN","CHOLAFIN","BAJAJHLDNG","IRCTC","ZOMATO",
            "NYKAA","PAYTM","POLICYBZR","DELHIVERY","CARTRADE",
            "IRFC","RVNL","HAL","BEL","BHEL","NMDC","SAIL",
            "VEDL","HINDZINC","NATIONALUM","MOIL","GMRINFRA",
            "BANDHANBNK","FEDERALBNK","IDFCFIRSTB","RBLBANK","PNB",
            "CANBK","UNIONBANK","BANKBARODA","IOB","UCOBANK",
            "OBEROIRLTY","DLF","GODREJPROP","PRESTIGE","BRIGADE",
            "PHOENIXLTD","SOBHA","MAHINDRA","M&M","ASHOKLEY",
            "TVSMOTOR","BALKRISIND","MRF","APOLLOTYRE","EXIDEIND"
        ]
        return [s + ".NS" for s in fallback]


def get_fno_symbols():
    """Get SEBI approved F&O stock symbols."""
    try:
        fno_stocks = fnolist()
        return [s.strip() + ".NS" for s in fno_stocks if s.strip()]
    except Exception as e:
        print(f"[F&O] Could not fetch live F&O list, using fallback: {e}")
        fallback = [
            "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","SBIN",
            "BHARTIARTL","BAJFINANCE","WIPRO","HCLTECH","TATAMOTORS",
            "TATASTEEL","ADANIENT","KOTAKBANK","AXISBANK","LT",
            "HINDUNILVR","MARUTI","SUNPHARMA","ONGC","ITC","NTPC",
            "POWERGRID","JSWSTEEL","HINDALCO","BAJAJFINSV","TECHM",
            "DRREDDY","CIPLA","DIVISLAB","EICHERMOT","HEROMOTOCO",
            "BAJAJ-AUTO","COALINDIA","BPCL","IOC","INDUSINDBK",
            "BANDHANBNK","FEDERALBNK","DLF","GODREJPROP","ZOMATO",
            "IRCTC","NYKAA","HAL","BEL","IRFC","RVNL","VEDL"
        ]
        return [s + ".NS" for s in fallback]


# ─────────────────────────────────────────────
#  FETCH PRICE DATA
# ─────────────────────────────────────────────
def fetch_stock_data(symbol: str, period: str = "3mo", interval: str = "1d"):
    """Fetch OHLCV data for a stock. Returns None silently on any failure."""
    import contextlib, io
    try:
        # Suppress yfinance's own print/warning output
        with contextlib.redirect_stderr(io.StringIO()):
            ticker = yf.Ticker(symbol)
            df     = ticker.history(period=period, interval=interval,
                                    auto_adjust=True)
        if df is None or df.empty or len(df) < 20:
            return None
        df.dropna(inplace=True)
        if len(df) < 15:
            return None
        return df
    except Exception:
        return None


# ─────────────────────────────────────────────
#  TECHNICAL INDICATORS
# ─────────────────────────────────────────────
def _find_col(df: pd.DataFrame, prefix: str) -> str:
    """Find column starting with prefix — handles any pandas-ta version."""
    for col in df.columns:
        if col.startswith(prefix):
            return col
    return None


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate RSI, MACD, Bollinger Bands, EMA, Volume spike.
    Each indicator is wrapped separately so one failure never
    blocks the others."""

    # RSI + EMA
    try:
        df["rsi"]   = ta.rsi(df["Close"], length=14)
        df["ema20"] = ta.ema(df["Close"], length=20)
        df["ema50"] = ta.ema(df["Close"], length=50)
    except Exception:
        pass

    # MACD — detect column names at runtime (varies by pandas-ta version)
    try:
        macd = ta.macd(df["Close"], fast=12, slow=26, signal=9)
        if macd is not None and not macd.empty:
            c = _find_col(macd, "MACD_")
            s = _find_col(macd, "MACDs_")
            h = _find_col(macd, "MACDh_")
            if c: df["macd"]        = macd[c]
            if s: df["macd_signal"] = macd[s]
            if h: df["macd_hist"]   = macd[h]
    except Exception:
        pass

    # Bollinger Bands — detect column names at runtime
    try:
        bb = ta.bbands(df["Close"], length=20, std=2)
        if bb is not None and not bb.empty:
            u = _find_col(bb, "BBU")
            l = _find_col(bb, "BBL")
            m = _find_col(bb, "BBM")
            if u: df["bb_upper"] = bb[u]
            if l: df["bb_lower"] = bb[l]
            if m: df["bb_mid"]   = bb[m]
    except Exception:
        pass

    # Volume spike
    try:
        df["vol_avg20"] = df["Volume"].rolling(20).mean()
        df["vol_spike"] = df["Volume"] > (df["vol_avg20"] * 1.5)
    except Exception:
        pass

    # ── Swing trading specific indicators ──

    # EMA 200 — long term trend direction
    try:
        df["ema200"] = ta.ema(df["Close"], length=200)
    except Exception:
        pass

    # ATR — Average True Range for realistic target/SL calculation
    try:
        df["atr"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    except Exception:
        pass

    # 52-week high and low (uses all available data)
    try:
        df["high_52w"] = df["High"].rolling(min(252, len(df))).max()
        df["low_52w"]  = df["Low"].rolling(min(252, len(df))).min()
    except Exception:
        pass

    # Weekly momentum — % change over last 5 trading days
    try:
        df["momentum_5d"]  = df["Close"].pct_change(5) * 100
        df["momentum_20d"] = df["Close"].pct_change(20) * 100
    except Exception:
        pass

    # Support and resistance — 20-day high/low
    try:
        df["resistance_20"] = df["High"].rolling(20).max()
        df["support_20"]    = df["Low"].rolling(20).min()
    except Exception:
        pass

    return df


# ─────────────────────────────────────────────
#  CONFIDENCE SCORE CALCULATOR
# ─────────────────────────────────────────────
def calculate_confidence(signals: list) -> int:
    """
    Each signal condition adds weight.
    Returns confidence as integer percentage.
    """
    weights = {
        "rsi_oversold":       20,
        "rsi_overbought":     20,
        "macd_bullish_cross": 25,
        "macd_bearish_cross": 25,
        "volume_spike":       20,
        "ema_bullish":        20,
        "ema_bearish":        20,
        "bb_lower_touch":     15,
        "bb_upper_touch":     15,
        "price_momentum":     15,
    }
    total = sum(weights.get(s, 10) for s in signals)
    # Cap at 95
    return min(int(total), 95)


# ─────────────────────────────────────────────
#  SIGNAL DETECTION — STOCKS
# ─────────────────────────────────────────────
def safe_float(value, default=0.0):
    """Safely convert a value to float. Returns default if None or NaN."""
    try:
        if value is None:
            return default
        v = float(value)
        import math
        return default if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return default


def detect_stock_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    SWING TRADING signal detection.
    Uses daily candles over 6-12 months.
    Targets 10-25% gains over 3-10 trading days.
    Minimum price ₹50, minimum volume 5 lakh per day.
    """
    try:
        if df is None or len(df) < 60:
            return None

        latest   = df.iloc[-1]
        prev     = df.iloc[-2]
        prev2    = df.iloc[-3] if len(df) > 3 else prev
        price    = round(safe_float(latest.get("Close"), 0.0), 2)
        avg_vol  = safe_float(latest.get("vol_avg20"), 0)

        # ── Basic filters ──
        if avg_vol < MIN_VOLUME:
            return None
        if price < MIN_PRICE:
            return None

        # ── Extract indicators ──
        rsi          = safe_float(latest.get("rsi"), 50)
        macd         = safe_float(latest.get("macd"), 0)
        macd_sig     = safe_float(latest.get("macd_signal"), 0)
        prev_macd    = safe_float(prev.get("macd"), 0)
        prev_msig    = safe_float(prev.get("macd_signal"), 0)
        ema20        = safe_float(latest.get("ema20"), price)
        ema50        = safe_float(latest.get("ema50"), price)
        ema200       = safe_float(latest.get("ema200"), price)
        vol_spike    = bool(latest.get("vol_spike", False))
        atr          = safe_float(latest.get("atr"), price * 0.02)
        mom_5d       = safe_float(latest.get("momentum_5d"), 0)
        mom_20d      = safe_float(latest.get("momentum_20d"), 0)
        resistance   = safe_float(latest.get("resistance_20"), price * 1.1)
        support      = safe_float(latest.get("support_20"), price * 0.9)
        high_52w     = safe_float(latest.get("high_52w"), price * 1.3)
        low_52w      = safe_float(latest.get("low_52w"), price * 0.7)

        # ── Trend context ──
        above_ema200  = price > ema200
        ema_aligned   = ema20 > ema50          # Bullish EMA stack
        near_52w_high = price >= high_52w * 0.95  # Within 5% of 52w high

        # ════════════════════════════════════════
        #  SWING BUY CONDITIONS
        #  Need 3+ of 6 conditions
        # ════════════════════════════════════════
        buy_signals = []

        # 1. RSI between 40-60 and rising (healthy, not overbought)
        prev_rsi = safe_float(prev.get("rsi"), 50)
        if 38 <= rsi <= 62 and rsi > prev_rsi:
            buy_signals.append("rsi_rising_healthy")

        # 2. MACD bullish crossover on daily chart
        if prev_macd < prev_msig and macd > macd_sig:
            buy_signals.append("macd_bullish_cross")

        # 3. Price above EMA20 and EMA50 — bullish trend
        if ema_aligned and price > ema20:
            buy_signals.append("ema_bullish_stack")

        # 4. Volume spike with price up — institutional buying
        if vol_spike and safe_float(latest.get("Close"), 0.0) > safe_float(prev.get("Close"), 0.0):
            buy_signals.append("volume_breakout")

        # 5. Breakout above 20-day resistance
        if price >= resistance * 0.99:
            buy_signals.append("resistance_breakout")

        # 6. Strong weekly momentum — stock already moving
        if 3.0 <= mom_5d <= 25.0:
            buy_signals.append("weekly_momentum")

        # 7. Price above EMA200 — long term bullish
        if above_ema200:
            buy_signals.append("above_ema200")

        # 8. Near 52-week high — strong stock
        if near_52w_high and vol_spike:
            buy_signals.append("52w_high_breakout")

        # ════════════════════════════════════════
        #  SWING SELL / SHORT CONDITIONS
        #  Need 3+ of 5 conditions
        # ════════════════════════════════════════
        sell_signals = []

        # 1. RSI falling from overbought
        if rsi > 65 and rsi < prev_rsi:
            sell_signals.append("rsi_falling_overbought")

        # 2. MACD bearish crossover
        if prev_macd > prev_msig and macd < macd_sig:
            sell_signals.append("macd_bearish_cross")

        # 3. Price below EMA20 and EMA50
        if not ema_aligned and price < ema20:
            sell_signals.append("ema_bearish_stack")

        # 4. Volume spike with price down — distribution
        if vol_spike and safe_float(latest.get("Close"), 0.0) < safe_float(prev.get("Close"), 0.0):
            sell_signals.append("volume_distribution")

        # 5. Break below 20-day support
        if price <= support * 1.01:
            sell_signals.append("support_breakdown")

        # 6. Negative weekly momentum
        if mom_5d <= -3.0:
            sell_signals.append("weekly_downtrend")

        # ── Determine direction — need 3+ signals ──
        signal_type    = None
        active_signals = []

        if len(buy_signals) >= 3:
            signal_type    = "BUY"
            active_signals = buy_signals
        elif len(sell_signals) >= 3:
            signal_type    = "SELL"
            active_signals = sell_signals

        if not signal_type:
            return None

        confidence = calculate_confidence(active_signals)
        if confidence < CONFIDENCE_THRESHOLD:
            return None

        # ════════════════════════════════════════
        #  SWING TARGET AND STOP LOSS CALCULATION
        #  Uses ATR for realistic swing targets
        #  Target: 10-25% gain typical
        # ════════════════════════════════════════
        if atr < price * 0.005:
            atr = price * 0.02   # Minimum 2% ATR

        if signal_type == "BUY":
            target    = round(price + (atr * ATR_TARGET_MULT), 2)
            stop_loss = round(price - (atr * ATR_SL_MULT), 2)
            # Ensure minimum 8% target, maximum 30%
            min_tgt   = round(price * 1.08, 2)
            max_tgt   = round(price * 1.30, 2)
            target    = max(target, min_tgt)
            target    = min(target, max_tgt)
        else:
            target    = round(price - (atr * ATR_TARGET_MULT), 2)
            stop_loss = round(price + (atr * ATR_SL_MULT), 2)
            max_tgt   = round(price * 0.92, 2)
            min_tgt   = round(price * 0.70, 2)
            target    = min(target, max_tgt)
            target    = max(target, min_tgt)

        gain_pct = round(abs((target - price) / price) * 100, 1)
        sl_pct   = round(abs((stop_loss - price) / price) * 100, 1)

        reason_map = {
            "rsi_rising_healthy":   "RSI rising in healthy zone",
            "macd_bullish_cross":   "MACD daily bullish crossover",
            "ema_bullish_stack":    "EMA20 > EMA50 bullish stack",
            "volume_breakout":      "Volume breakout — institutional buying",
            "resistance_breakout":  "Breaking above 20-day resistance",
            "weekly_momentum":      "Strong weekly price momentum",
            "above_ema200":         "Price above EMA200 — uptrend confirmed",
            "52w_high_breakout":    "Near 52-week high with volume",
            "rsi_falling_overbought": "RSI falling from overbought",
            "macd_bearish_cross":   "MACD daily bearish crossover",
            "ema_bearish_stack":    "EMA bearish — downtrend",
            "volume_distribution":  "Volume distribution — selling pressure",
            "support_breakdown":    "Breaking below 20-day support",
            "weekly_downtrend":     "Negative weekly momentum",
        }
        reason = " + ".join(reason_map.get(s, s) for s in active_signals[:3])

        return {
            "date":         date.today().strftime("%d-%m-%Y"),
            "time":         datetime.now(india).strftime("%H:%M"),
            "stock":        symbol.replace(".NS", "").replace(".BO", ""),
            "exchange":     "NSE" if ".NS" in symbol else "BSE",
            "signal_type":  signal_type,
            "entry_price":  price,
            "target":       target,
            "stop_loss":    stop_loss,
            "confidence":   confidence,
            "rsi":          round(rsi, 1),
            "gain_pct":     gain_pct,
            "sl_pct":       sl_pct,
            "hold_days":    SWING_HOLD_DAYS,
            "atr":          round(atr, 2),
            "macd_cross":   "macd_bullish_cross" in active_signals
                            or "macd_bearish_cross" in active_signals,
            "volume_spike": vol_spike,
            "reason":       reason,
            "status":       "Open",
        }

    except Exception as e:
        print(f"[Swing Signal] Error on {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
#  SIGNAL DETECTION — F&O
# ─────────────────────────────────────────────
def detect_fo_signal(symbol: str, df: pd.DataFrame) -> dict | None:
    """
    Detect F&O specific signals for options trading.
    Returns signal with strike price and premium estimates.
    """
    try:
        stock_signal = detect_stock_signal(symbol, df)
        if not stock_signal:
            return None

        price       = stock_signal["entry_price"]
        signal_type = stock_signal["signal_type"]
        confidence  = stock_signal["confidence"]

        if confidence < 65:
            return None

        # ── Estimate option details ──
        # Round to nearest strike (every ₹50 for most stocks)
        strike_interval = 50 if price > 500 else 10 if price > 100 else 5
        if signal_type == "BUY":
            option_type = "CE"  # Call option
            strike      = round(price / strike_interval) * strike_interval
        else:
            option_type = "PE"  # Put option
            strike      = round(price / strike_interval) * strike_interval

        # Estimate premium (rough approximation for testing)
        # Real implementation needs live option chain data
        intrinsic   = abs(price - strike)
        time_value  = price * 0.015
        premium     = round(intrinsic + time_value, 1)
        tgt_premium = round(premium * 1.6, 1)
        sl_premium  = round(premium * 0.5, 1)

        # Next weekly expiry (Thursday)
        today       = datetime.now(india)
        days_to_thu = (3 - today.weekday()) % 7
        if days_to_thu == 0:
            days_to_thu = 7
        expiry_date = (today + pd.Timedelta(days=days_to_thu)).strftime("%d %b")

        stock_signal["fo_option_type"]  = option_type
        stock_signal["fo_strike"]       = strike
        stock_signal["fo_expiry"]       = expiry_date
        stock_signal["fo_premium"]      = premium
        stock_signal["fo_tgt_premium"]  = tgt_premium
        stock_signal["fo_sl_premium"]   = sl_premium
        stock_signal["signal_category"] = "F&O"

        return stock_signal

    except Exception as e:
        print(f"[F&O Signal] Error on {symbol}: {e}")
        return None


# ─────────────────────────────────────────────
#  TELEGRAM MESSAGE FORMATTERS
# ─────────────────────────────────────────────
def format_stock_message(sig: dict) -> str:
    arrow      = "🟢" if sig["signal_type"] == "BUY" else "🔴"
    action     = "BUY"  if sig["signal_type"] == "BUY" else "SELL"
    gain_pct   = sig.get("gain_pct", "")
    sl_pct     = sig.get("sl_pct", "")
    hold_days  = sig.get("hold_days", "3-7")
    gain_str   = f"  (+{gain_pct}%)" if gain_pct else ""
    sl_str     = f"  (-{sl_pct}%)"   if sl_pct   else ""
    return (
        f"{arrow} <b>SWING {action} — {sig['stock']} ({sig['exchange']})</b>\n\n"
        f"💰 Entry:      ₹{sig['entry_price']}\n"
        f"🎯 Target:     ₹{sig['target']}{gain_str}\n"
        f"🛑 Stop loss:  ₹{sig['stop_loss']}{sl_str}\n"
        f"📅 Hold time:  {hold_days} trading days\n"
        f"📊 Confidence: {sig['confidence']}%\n"
        f"📈 RSI:        {sig['rsi']}\n\n"
        f"📋 <b>Reason:</b> {sig['reason']}\n\n"
        f"⏰ {sig['date']} at {sig['time']}\n"
        f"⚠️ Educational only. Not financial advice."
    )


def format_fo_message(sig: dict) -> str:
    arrow = "🟢" if sig["signal_type"] == "BUY" else "🔴"
    return (
        f"{arrow} <b>F&O SIGNAL — {sig['stock']} {sig['fo_strike']} {sig['fo_option_type']}</b>\n\n"
        f"📅 Expiry:        {sig['fo_expiry']}\n"
        f"💰 Buy premium:  ₹{sig['fo_premium']}\n"
        f"🎯 Target prem:  ₹{sig['fo_tgt_premium']}\n"
        f"🛑 SL premium:   ₹{sig['fo_sl_premium']}\n"
        f"📊 Confidence:   {sig['confidence']}%\n"
        f"📈 RSI:          {sig['rsi']}\n\n"
        f"📋 <b>Reason:</b> {sig['reason']}\n\n"
        f"⏰ {sig['date']} at {sig['time']}\n"
        f"⚠️ F&O trading involves high risk. Not financial advice."
    )


def format_daily_summary(total: int, buy: int, sell: int, fo: int) -> str:
    return (
        f"📊 <b>Daily Signal Summary</b>\n\n"
        f"📅 Date: {date.today().strftime('%d %b %Y')}\n\n"
        f"Total signals generated: {total}\n"
        f"🟢 Buy signals:  {buy}\n"
        f"🔴 Sell signals: {sell}\n"
        f"📈 F&O signals:  {fo}\n\n"
        f"All signals logged to signals_log.csv\n"
        f"Update results in Google Sheet weekly."
    )


# ─────────────────────────────────────────────
#  PHASE 1 — MORNING FILTER SCAN
# ─────────────────────────────────────────────
def morning_filter_scan():
    """
    Runs once at 9:00 AM on trading days only.
    Blocked automatically on weekends and NSE holidays.
    Scans ALL NSE + BSE stocks and builds the daily watchlist.
    """
    # ── Holiday gate ──
    if is_market_holiday():
        holiday  = get_holiday_name()
        next_day = get_next_trading_day()
        msg = (
            f"🏖️ <b>Market Holiday — {holiday}</b>\n\n"
            f"📅 {date.today().strftime('%d %b %Y')}\n"
            f"NSE and BSE are closed today.\n"
            f"No signals will be generated.\n\n"
            f"📅 <b>Next trading day: {next_day}</b>\n"
            f"Signal engine resumes automatically at 9:00 AM."
        )
        print(f"[Morning Scan] Holiday ({holiday}) — next trading day: {next_day}")
        send_telegram(msg)
        return
    print("\n" + "="*50)
    print(f"[{datetime.now(india).strftime('%H:%M')}] MORNING SCAN STARTED")
    print("="*50)

    # Clear today's signal tracker — fresh start each trading day
    global _signals_sent_today
    _signals_sent_today = set()
    print("[Morning Scan] Signal tracker cleared — fresh day.")

    send_telegram(
        f"🌅 <b>Morning Scan Started</b>\n"
        f"⏰ {datetime.now(india).strftime('%I:%M %p')}\n"
        f"Scanning all NSE + BSE stocks...\nThis takes 10–15 minutes."
    )

    all_symbols  = get_all_nse_symbols()
    fno_symbols  = set(get_fno_symbols())
    watchlist    = []
    total        = len(all_symbols)

    print(f"Total symbols to scan: {total}")

    for i, symbol in enumerate(all_symbols):
        try:
            # Swing trading needs 1 year of daily data
            df = fetch_stock_data(symbol, period="1y", interval="1d")
            if df is None or len(df) < 50:
                continue

            price    = float(df["Close"].iloc[-1])
            avg_vol  = float(df["Volume"].rolling(20).mean().iloc[-1])
            mom_5d   = float(df["Close"].pct_change(5).iloc[-1]) * 100
            mom_20d  = float(df["Close"].pct_change(20).iloc[-1]) * 100

            # Swing filters — stricter than intraday
            if price < MIN_PRICE:
                continue
            if avg_vol < MIN_VOLUME:
                continue

            df  = calculate_indicators(df)
            rsi = float(df["rsi"].iloc[-1]) if "rsi" in df.columns else 50

            # Swing watchlist criteria:
            # — Strong weekly momentum (moving)
            # — OR RSI in actionable zone
            # — OR near resistance/support
            ema20 = float(df["ema20"].iloc[-1]) if "ema20" in df.columns else price
            ema50 = float(df["ema50"].iloc[-1]) if "ema50" in df.columns else price
            near_ema = abs(price - ema20) / price < 0.03   # within 3% of EMA20

            qualifies = (
                abs(mom_5d) > 3.0       # Moving 3%+ this week
                or abs(mom_20d) > 8.0   # Moving 8%+ this month
                or (38 <= rsi <= 62)    # RSI in swing zone
                or near_ema             # Near EMA20 — potential entry
            )

            if qualifies:
                watchlist.append({
                    "symbol":   symbol,
                    "price":    round(price, 2),
                    "avg_vol":  avg_vol,
                    "mom_5d":   round(mom_5d, 2),
                    "mom_20d":  round(mom_20d, 2),
                    "rsi":      round(rsi, 1),
                    "is_fno":   symbol in fno_symbols
                })

            if (i + 1) % 100 == 0:
                print(f"  Scanned {i+1}/{total} — watchlist: {len(watchlist)}")

            time.sleep(0.3)

        except Exception as e:
            print(f"  Skip {symbol}: {e}")
            continue

    # Save watchlist
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f)

    msg = (
        f"✅ <b>Morning Scan Complete</b>\n\n"
        f"Total scanned: {total}\n"
        f"Watchlist for today: {len(watchlist)} stocks\n"
        f"F&O eligible in list: {sum(1 for s in watchlist if s['is_fno'])}\n\n"
        f"Intraday scans will now run every 30 minutes."
    )
    send_telegram(msg)
    print(f"\n[Morning Scan] Done. Watchlist: {len(watchlist)} stocks")
    return watchlist


# ─────────────────────────────────────────────
#  PHASE 2 — INTRADAY SIGNAL SCAN
# ─────────────────────────────────────────────
def intraday_signal_scan():
    """
    Runs every 30 minutes during market hours (9:15 AM – 3:30 PM).
    Blocked on weekends and NSE/BSE holidays.
    Scans only watchlist stocks for live signals.
    """
    now = datetime.now(india)
    hour, minute = now.hour, now.minute

    # ── Holiday gate ──
    if is_market_holiday():
        print(f"[{now.strftime('%H:%M')}] Holiday — stock scan skipped.")
        return

    # Only run during market hours
    if not ((9 <= hour < 15) or (hour == 15 and minute <= 30)):
        print(f"[{now.strftime('%H:%M')}] Market closed. Skipping scan.")
        return

    print(f"\n[{now.strftime('%H:%M')}] INTRADAY SCAN STARTED")

    # Load watchlist
    if not os.path.isfile(WATCHLIST_FILE):
        print("[Intraday] No watchlist found. Run morning scan first.")
        return

    with open(WATCHLIST_FILE, "r") as f:
        watchlist = json.load(f)

    if not watchlist:
        print("[Intraday] Watchlist is empty.")
        return

    buy_count  = 0
    sell_count = 0
    fo_count   = 0
    fno_set    = set(get_fno_symbols())

    for item in watchlist:
        symbol = item["symbol"]
        try:
            # Swing trading uses daily candles — 1 year of data
            df = fetch_stock_data(symbol, period="1y", interval="1d")
            if df is None or len(df) < 50:
                continue

            df = calculate_indicators(df)

            # ── Stock signal ──
            sig = detect_stock_signal(symbol, df)
            if sig:
                sig_key = f"{sig['stock']}_{sig['signal_type']}"
                if sig_key in _signals_sent_today:
                    # Already sent this signal today — skip silently
                    pass
                else:
                    _signals_sent_today.add(sig_key)
                    log_signal(sig)
                    send_telegram(format_stock_message(sig))
                    add_open_position(sig)
                    if sig["signal_type"] == "BUY":
                        buy_count += 1
                    else:
                        sell_count += 1
                    time.sleep(1)

            # ── F&O signal (only for F&O eligible stocks) ──
            if symbol in fno_set:
                fo_sig = detect_fo_signal(symbol, df)
                if fo_sig and fo_sig != sig:
                    fo_key = f"{fo_sig['stock']}_FO_{fo_sig.get('fo_option_type','')}"
                    if fo_key not in _signals_sent_today:
                        _signals_sent_today.add(fo_key)
                        log_signal(fo_sig)
                        send_telegram(format_fo_message(fo_sig))
                        add_open_position(fo_sig)
                        fo_count += 1
                        time.sleep(1)

            time.sleep(0.5)

        except Exception as e:
            print(f"  Skip {symbol}: {e}")
            continue

    total = buy_count + sell_count + fo_count
    print(f"[Intraday Stocks] Done. Buy:{buy_count} Sell:{sell_count} Stock F&O:{fo_count}")

    if total > 0:
        summary = (
            f"⚡ <b>Stock Scan Done — {now.strftime('%I:%M %p')}</b>\n"
            f"🟢 Buy: {buy_count}  🔴 Sell: {sell_count}  📈 Stock F&O: {fo_count}"
        )
        send_telegram(summary)


# ─────────────────────────────────────────────
#  INDEX F&O MODULE
#  Nifty / BankNifty / Sensex / FinNifty / MidcapNifty
# ─────────────────────────────────────────────

# Index definitions — symbol, display name, strike interval, expiry weekday
# weekday: 0=Monday 1=Tuesday 2=Wednesday 3=Thursday 4=Friday
INDEX_CONFIG = {
    "^NSEI": {
        "name":             "NIFTY",
        "display":          "NIFTY 50",
        "strike_interval":  50,
        "expiry_weekday":   3,   # Thursday
        "expiry_label":     "Weekly Thu",
        "lot_size":         50,
        "fallback":         ["^NSEI", "NIFTY50.NS"],
    },
    "^NSEBANK": {
        "name":             "BANKNIFTY",
        "display":          "BANK NIFTY",
        "strike_interval":  100,
        "expiry_weekday":   2,   # Wednesday
        "expiry_label":     "Weekly Wed",
        "lot_size":         15,
        "fallback":         ["^NSEBANK", "BANKNIFTY.NS"],
    },
    "^BSESN": {
        "name":             "SENSEX",
        "display":          "SENSEX",
        "strike_interval":  100,
        "expiry_weekday":   4,   # Friday
        "expiry_label":     "Weekly Fri",
        "lot_size":         10,
        "fallback":         ["^BSESN", "^BSESN"],
    },
    "NIFTY_FIN_SERVICE.NS": {
        "name":             "FINNIFTY",
        "display":          "FIN NIFTY",
        "strike_interval":  50,
        "expiry_weekday":   1,   # Tuesday
        "expiry_label":     "Weekly Tue",
        "lot_size":         40,
        # ^CNXFIN is a reliable fallback for FinNifty
        "fallback":         ["NIFTY_FIN_SERVICE.NS", "^CNXFIN",
                             "NIFTYFINSRV25_50.NS"],
    },
    "NIFTY_MID_SELECT.NS": {
        "name":             "MIDCAPNIFTY",
        "display":          "MIDCAP NIFTY",
        "strike_interval":  25,
        "expiry_weekday":   0,   # Monday
        "expiry_label":     "Weekly Mon",
        "lot_size":         75,
        # Multiple fallbacks — yfinance is inconsistent for this index
        "fallback":         ["NIFTY_MID_SELECT.NS", "^NSEMDCP50",
                             "NIFTYMIDCAP150.NS", "^CRSMID"],
    },
}


def fetch_index_data(symbol: str, config: dict,
                     period: str = "3mo", interval: str = "1d"):
    """
    Fetch index data trying primary symbol first, then all fallbacks.
    Returns (dataframe, symbol_used) or (None, None) if all fail.
    """
    import contextlib, io

    symbols_to_try = [symbol] + [
        s for s in config.get("fallback", []) if s != symbol
    ]
    # Remove duplicates while preserving order
    seen = set()
    symbols_to_try = [
        s for s in symbols_to_try
        if not (s in seen or seen.add(s))
    ]

    for sym in symbols_to_try:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                ticker = yf.Ticker(sym)
                df     = ticker.history(period=period, interval=interval,
                                        auto_adjust=True)
            if df is not None and not df.empty and len(df) >= 10:
                df.dropna(inplace=True)
                if len(df) >= 10:
                    print(f"    [{config['display']}] Data fetched "
                          f"via {sym} ({len(df)} rows)")
                    return df, sym
        except Exception:
            continue

    print(f"    [{config['display']}] All symbols failed: {symbols_to_try}")
    return None, None


def get_next_expiry(expiry_weekday: int) -> str:
    """
    Calculate the next expiry date for a given weekday.
    expiry_weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    Returns date string like '03 Apr'
    """
    today     = datetime.now(india)
    days_ahead = expiry_weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    expiry = today + pd.Timedelta(days=days_ahead)
    return expiry.strftime("%d %b")


def get_next_monthly_expiry(expiry_weekday: int) -> str:
    """
    Get last Thursday (or given weekday) of current/next month.
    Used for monthly expiry signals.
    """
    today = datetime.now(india)
    # Find last occurrence of weekday in current month
    import calendar
    year, month = today.year, today.month
    last_day = calendar.monthrange(year, month)[1]
    for day in range(last_day, 0, -1):
        d = datetime(year, month, day)
        if d.weekday() == expiry_weekday:
            if d.date() > today.date():
                return d.strftime("%d %b")
            break
    # Move to next month
    if month == 12:
        month, year = 1, year + 1
    else:
        month += 1
    last_day = calendar.monthrange(year, month)[1]
    for day in range(last_day, 0, -1):
        d = datetime(year, month, day)
        if d.weekday() == expiry_weekday:
            return d.strftime("%d %b")
    return "Last Thu"


def round_to_strike(price: float, interval: int, signal_type: str) -> int:
    """
    Round index price to nearest valid strike price.
    For BUY — round to nearest ATM or slightly OTM call.
    For SELL — round to nearest ATM or slightly OTM put.
    """
    base = round(price / interval) * interval
    if signal_type == "BUY":
        # ATM call or slight OTM
        return int(base)
    else:
        # ATM put or slight OTM
        return int(base)


def estimate_index_premium(index_price: float, strike: int,
                            option_type: str, days_to_expiry: int) -> dict:
    """
    Estimate option premium using simplified Black-Scholes approximation.
    For testing purposes — real implementation needs live option chain.

    Returns dict with premium, target, stop_loss, expected_move_pct
    """
    # Intrinsic value
    if option_type == "CE":
        intrinsic = max(0, index_price - strike)
    else:
        intrinsic = max(0, strike - index_price)

    # Time value approximation
    # Volatility assumption: ~15% annual for Nifty, ~20% for BankNifty
    vol_map = {"^NSEI": 0.15, "^NSEBANK": 0.20, "^BSESN": 0.15,
               "NIFTY_FIN_SERVICE.NS": 0.18, "NIFTY_MID_SELECT.NS": 0.22}

    # Use 17% as default
    annual_vol   = 0.17
    daily_vol    = annual_vol / (252 ** 0.5)
    time_val     = index_price * daily_vol * (days_to_expiry ** 0.5)

    premium      = round(intrinsic + time_val, 1)
    if premium < 5:
        premium = 5.0

    # Target = 60-80% gain on premium (realistic for index options)
    target_prem  = round(premium * 1.70, 1)
    sl_prem      = round(premium * 0.45, 1)

    # Expected move in index points
    expected_move = round(index_price * daily_vol * (days_to_expiry ** 0.5), 0)

    return {
        "premium":       premium,
        "target_prem":   target_prem,
        "sl_prem":       sl_prem,
        "expected_move": int(expected_move),
    }


# ─────────────────────────────────────────────
#  INDIA VIX FETCHER
#  VIX = volatility index — measures market fear
#  Symbol on Yahoo Finance: ^INDIAVIX
# ─────────────────────────────────────────────

def fetch_india_vix() -> dict:
    """
    Fetch India VIX data from Yahoo Finance.
    Returns dict with current VIX, trend, and signal interpretation.
    VIX below 13  = very low fear = possible complacency = caution
    VIX 13-18     = normal range = healthy market
    VIX 18-22     = elevated fear = potential buying opportunity
    VIX above 22  = high fear = strong buy signal for calls on recovery
    VIX falling   = market stabilising = bullish for calls
    VIX rising    = fear increasing = bullish for puts
    """
    try:
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.Ticker("^INDIAVIX").history(period="30d", interval="1d")

        if df is None or df.empty or len(df) < 5:
            return {"available": False}

        current_vix  = round(float(df["Close"].iloc[-1]), 2)
        prev_vix     = round(float(df["Close"].iloc[-2]), 2)
        vix_5d_avg   = round(float(df["Close"].iloc[-5:].mean()), 2)
        vix_change   = round(current_vix - prev_vix, 2)
        vix_trend    = "RISING" if current_vix > vix_5d_avg else "FALLING"

        # Interpret VIX level
        if current_vix < 12:
            level       = "VERY LOW"
            market_mood = "Complacency — be cautious"
            bias        = "NEUTRAL"
        elif current_vix < 16:
            level       = "LOW"
            market_mood = "Market calm — normal conditions"
            bias        = "BULLISH" if vix_trend == "FALLING" else "NEUTRAL"
        elif current_vix < 20:
            level       = "MODERATE"
            market_mood = "Some fear — potential opportunity"
            bias        = "BULLISH" if vix_trend == "FALLING" else "CAUTIOUS"
        elif current_vix < 28:
            level       = "HIGH"
            market_mood = "Elevated fear — PUT signals likely, CALL caution"
            # High VIX rising = good for PUT signals, not WAIT
            bias        = "BULLISH" if vix_trend == "FALLING" else "BEARISH"
        else:
            level       = "VERY HIGH"
            market_mood = "Extreme panic — only PUT signals, no CALL"
            # Even at extreme VIX, allow PUT (SELL) signals
            bias        = "BEARISH"

        # VIX signal for options
        # When VIX falls from high levels — buy calls (market recovering)
        # When VIX spikes sharply — buy puts (market falling)
        # Never return WAIT — always give a directional signal
        vix_signal = None
        if vix_trend == "FALLING" and current_vix > 16:
            vix_signal = "BUY"       # VIX falling from elevated = calls
        elif vix_change > 1.0 or current_vix > 20:
            vix_signal = "SELL"      # VIX spike or elevated = puts
        elif vix_trend == "FALLING" and current_vix < 14:
            vix_signal = "NEUTRAL"   # VIX too low — no strong signal

        return {
            "available":    True,
            "current":      current_vix,
            "prev":         prev_vix,
            "change":       vix_change,
            "trend":        vix_trend,
            "level":        level,
            "mood":         market_mood,
            "bias":         bias,
            "vix_signal":   vix_signal,
            "5d_avg":       vix_5d_avg,
        }

    except Exception as e:
        print(f"  [VIX] Fetch error: {e}")
        return {"available": False}


def get_support_resistance(df: pd.DataFrame, price: float) -> dict:
    """
    Calculate key support and resistance levels from daily price data.
    Uses previous week high/low, previous month high/low,
    and pivot point calculation.
    """
    try:
        if len(df) < 10:
            return {}

        # Previous week levels (last 5 trading days)
        prev_week      = df.iloc[-6:-1]
        week_high      = round(float(prev_week["High"].max()), 2)
        week_low       = round(float(prev_week["Low"].min()), 2)
        week_close     = round(float(prev_week["Close"].iloc[-1]), 2)

        # Previous month levels (last 22 trading days)
        prev_month     = df.iloc[-23:-1]
        month_high     = round(float(prev_month["High"].max()), 2)
        month_low      = round(float(prev_month["Low"].min()), 2)

        # Classic pivot point
        pivot  = round((week_high + week_low + week_close) / 3, 2)
        r1     = round(2 * pivot - week_low, 2)
        r2     = round(pivot + (week_high - week_low), 2)
        s1     = round(2 * pivot - week_high, 2)
        s2     = round(pivot - (week_high - week_low), 2)

        # Nearest resistance above price
        resistance_levels = sorted([r for r in [r1, r2, week_high, month_high]
                                     if r > price])
        nearest_resistance = resistance_levels[0] if resistance_levels else round(price * 1.05, 2)

        # Nearest support below price
        support_levels = sorted([s for s in [s1, s2, week_low, month_low]
                                   if s < price], reverse=True)
        nearest_support = support_levels[0] if support_levels else round(price * 0.95, 2)

        # Is price near key level?
        near_resistance  = price >= nearest_resistance * 0.98
        near_support     = price <= nearest_support * 1.02
        above_pivot      = price > pivot
        breakout_above   = price > week_high
        breakdown_below  = price < week_low

        return {
            "pivot":              pivot,
            "r1": r1, "r2": r2,
            "s1": s1, "s2": s2,
            "week_high":          week_high,
            "week_low":           week_low,
            "month_high":         month_high,
            "month_low":          month_low,
            "nearest_resistance": nearest_resistance,
            "nearest_support":    nearest_support,
            "near_resistance":    near_resistance,
            "near_support":       near_support,
            "above_pivot":        above_pivot,
            "breakout_above":     breakout_above,
            "breakdown_below":    breakdown_below,
        }

    except Exception as e:
        print(f"  [SR] Error: {e}")
        return {}


def detect_index_fo_signal(symbol: str, config: dict) -> dict | None:
    """
    Index F&O signal detection using:
    1. India VIX — market fear gauge
    2. Support / Resistance levels — key price zones
    3. Daily trend — EMA and MACD on daily chart
    4. Weekly momentum — are institutions buying or selling
    This combination is far more reliable than intraday indicators.
    """
    try:
        print(f"  Scanning index: {config['display']}")

        # ── Fetch 6 months daily data ──
        df_daily, sym_used = fetch_index_data(
            symbol, config, period="6mo", interval="1d"
        )
        if df_daily is None or len(df_daily) < 20:
            print(f"  No data for {config['display']}")
            return None

        df_daily = calculate_indicators(df_daily)

        latest     = df_daily.iloc[-1]
        prev       = df_daily.iloc[-2]
        price      = round(safe_float(latest.get("Close"), 0.0), 2)

        # ── Daily indicators ──
        rsi       = safe_float(latest.get("rsi"), 50)
        prev_rsi  = safe_float(prev.get("rsi"), 50)
        macd      = safe_float(latest.get("macd"), 0)
        macd_sig  = safe_float(latest.get("macd_signal"), 0)
        prev_macd = safe_float(prev.get("macd"), 0)
        prev_msig = safe_float(prev.get("macd_signal"), 0)
        ema20     = safe_float(latest.get("ema20"), price)
        ema50     = safe_float(latest.get("ema50"), price)
        vol_spike = bool(latest.get("vol_spike", False))

        # Weekly and monthly momentum
        mom_5d  = float(df_daily["Close"].pct_change(5).iloc[-1]) * 100
        mom_20d = float(df_daily["Close"].pct_change(20).iloc[-1]) * 100

        # ── India VIX ──
        vix = fetch_india_vix()

        # ── Support / Resistance ──
        sr = get_support_resistance(df_daily, price)

        # ════════════════════════════════════════
        #  BUY (CALL) signal logic
        #  Needs 3+ of these conditions
        # ════════════════════════════════════════
        buy_signals  = []
        buy_reasons  = []

        # 1. MACD bullish crossover on daily
        if prev_macd < prev_msig and macd > macd_sig:
            buy_signals.append("macd_cross_bullish")
            buy_reasons.append("MACD daily bullish crossover")

        # 2. RSI rising in healthy zone (not overbought)
        if 38 <= rsi <= 62 and rsi > prev_rsi:
            buy_signals.append("rsi_rising")
            buy_reasons.append(f"RSI rising ({round(rsi,1)})")

        # 3. Price above EMA20 — short term bullish
        if price > ema20 and ema20 > ema50:
            buy_signals.append("ema_bullish")
            buy_reasons.append("Price above EMA20 > EMA50")

        # 4. Breakout above weekly high — strong momentum
        if sr.get("breakout_above"):
            buy_signals.append("weekly_breakout")
            buy_reasons.append(f"Breakout above week high {sr.get('week_high', '')}")

        # 5. Price above pivot — bullish bias
        if sr.get("above_pivot"):
            buy_signals.append("above_pivot")
            buy_reasons.append(f"Above weekly pivot {sr.get('pivot', '')}")

        # 6. VIX falling from elevated levels — market recovering
        if vix.get("available") and vix.get("vix_signal") == "BUY":
            buy_signals.append("vix_bullish")
            buy_reasons.append(
                f"India VIX {vix['current']} falling — fear reducing"
            )

        # 7. Positive weekly momentum
        if mom_5d > 1.5:
            buy_signals.append("weekly_momentum_up")
            buy_reasons.append(f"Weekly momentum +{round(mom_5d,1)}%")

        # 8. Near support — good risk/reward for calls
        if sr.get("near_support"):
            buy_signals.append("near_support")
            buy_reasons.append(
                f"Near support ₹{sr.get('nearest_support', '')}"
            )

        # ════════════════════════════════════════
        #  SELL (PUT) signal logic
        #  Needs 3+ of these conditions
        # ════════════════════════════════════════
        sell_signals = []
        sell_reasons = []

        # 1. MACD bearish crossover on daily
        if prev_macd > prev_msig and macd < macd_sig:
            sell_signals.append("macd_cross_bearish")
            sell_reasons.append("MACD daily bearish crossover")

        # 2. RSI falling from overbought
        if rsi > 60 and rsi < prev_rsi:
            sell_signals.append("rsi_falling")
            sell_reasons.append(f"RSI falling from overbought ({round(rsi,1)})")

        # 3. Price below EMA20 — short term bearish
        if price < ema20 and ema20 < ema50:
            sell_signals.append("ema_bearish")
            sell_reasons.append("Price below EMA20 < EMA50")

        # 4. Breakdown below weekly low
        if sr.get("breakdown_below"):
            sell_signals.append("weekly_breakdown")
            sell_reasons.append(
                f"Breakdown below week low {sr.get('week_low', '')}"
            )

        # 5. Below pivot — bearish bias
        if not sr.get("above_pivot"):
            sell_signals.append("below_pivot")
            sell_reasons.append(f"Below weekly pivot {sr.get('pivot', '')}")

        # 6. VIX spiking — market fear increasing
        if vix.get("available") and vix.get("vix_signal") == "SELL":
            sell_signals.append("vix_spike")
            sell_reasons.append(
                f"India VIX {vix['current']} spiking — fear rising"
            )

        # 7. Negative weekly momentum
        if mom_5d < -1.5:
            sell_signals.append("weekly_momentum_down")
            sell_reasons.append(f"Weekly momentum {round(mom_5d,1)}%")

        # 8. Near resistance — good risk/reward for puts
        if sr.get("near_resistance"):
            sell_signals.append("near_resistance")
            sell_reasons.append(
                f"Near resistance {sr.get('nearest_resistance', '')}"
            )

        # ── VIX direction filter ──
        # On very high VIX — block BUY/CALL signals, allow SELL/PUT
        vix_available = vix.get("available", False)
        vix_bias      = vix.get("bias", "NEUTRAL")
        vix_current   = vix.get("current", 15)

        # Block CALL signals only if VIX is very high AND rising
        if vix_available and vix_bias == "BEARISH" and vix_current > 22:
            if len(buy_signals) < len(sell_signals):
                # Sell signals are stronger — let it proceed
                pass
            elif len(buy_signals) > 0 and len(sell_signals) == 0:
                print(f"  [{config['display']}] High VIX ({vix_current}) "
                      f"+ bearish bias — suppressing CALL signal, watching for PUT")
                buy_signals = []  # Clear buy signals on high VIX bearish day

        # ── Determine direction — need 2+ signals ──
        signal_type    = None
        active_signals = []
        active_reasons = []

        if len(buy_signals) >= 2:
            signal_type    = "BUY"
            active_signals = buy_signals
            active_reasons = buy_reasons
        elif len(sell_signals) >= 2:
            signal_type    = "SELL"
            active_signals = sell_signals
            active_reasons = sell_reasons

        # ── Debug print — shows condition count every scan ──
        vix_dbg = f"VIX:{vix.get('current','N/A')}({vix.get('trend','?')})"                   if vix.get("available") else "VIX:unavailable"
        print(f"    {config['display']} — BUY conditions:{len(buy_signals)} "
              f"SELL conditions:{len(sell_signals)} {vix_dbg}")

        if not signal_type:
            return None

        confidence = min(calculate_confidence(active_signals), 95)
        if confidence < 65:
            print(f"    {config['display']} — confidence {confidence}% below 65% threshold")
            return None

        # ── Option details ──
        interval       = config["strike_interval"]
        expiry_weekday = config["expiry_weekday"]
        option_type    = "CE" if signal_type == "BUY" else "PE"
        strike         = round_to_strike(price, interval, signal_type)
        weekly_expiry  = get_next_expiry(expiry_weekday)
        monthly_expiry = get_next_monthly_expiry(expiry_weekday)

        today          = datetime.now(india)
        days_ahead     = expiry_weekday - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        days_to_expiry = max(days_ahead, 1)

        premiums       = estimate_index_premium(
            price, strike, option_type, days_to_expiry
        )

        # Targets based on support/resistance + ATR minimum distance
        atr_daily = float(
            df_daily["High"].iloc[-10:].max() - df_daily["Low"].iloc[-10:].min()
        ) / 10
        # Minimum move: ATR * 1.5 to ensure meaningful target
        min_move = atr_daily * 1.5

        if signal_type == "BUY":
            sr_target   = sr.get("nearest_resistance", 0)
            atr_target  = round(price + min_move, 0)
            # Use SR target only if it is meaningfully above price (> 0.5%)
            if sr_target and sr_target > price * 1.005:
                index_target = round(sr_target, 0)
            else:
                index_target = atr_target

            sr_sl       = sr.get("nearest_support", 0)
            atr_sl      = round(price - (atr_daily * 0.8), 0)
            if sr_sl and sr_sl < price * 0.998:
                index_stop_loss = round(sr_sl, 0)
            else:
                index_stop_loss = atr_sl

        else:  # SELL / PUT
            sr_target   = sr.get("nearest_support", 0)
            atr_target  = round(price - min_move, 0)
            # Use SR target only if it is meaningfully below price (> 0.5%)
            if sr_target and sr_target < price * 0.995:
                index_target = round(sr_target, 0)
            else:
                index_target = atr_target

            sr_sl       = sr.get("nearest_resistance", 0)
            atr_sl      = round(price + (atr_daily * 0.8), 0)
            if sr_sl and sr_sl > price * 1.002:
                index_stop_loss = round(sr_sl, 0)
            else:
                index_stop_loss = atr_sl

        # Calculate gain and risk percentages
        gain_pct = round(abs((index_target - price) / price) * 100, 2)
        risk_pct = round(abs((index_stop_loss - price) / price) * 100, 2)

        reason = " + ".join(active_reasons[:3])

        # VIX info string for message
        vix_str = ""
        if vix.get("available"):
            vix_str = (
                f"\n📊 India VIX:  {vix['current']} "
                f"({vix['trend']}) — {vix['level']}"
            )

        return {
            "date":             date.today().strftime("%d-%m-%Y"),
            "time":             datetime.now(india).strftime("%H:%M"),
            "stock":            config["name"],
            "display_name":     config["display"],
            "exchange":         "NSE" if "BSESN" not in symbol else "BSE",
            "signal_type":      signal_type,
            "signal_category":  "INDEX_FO",
            "index_price":      price,
            "index_target":     int(index_target),
            "index_stop_loss":  int(index_stop_loss),
            "entry_price":      price,
            "target":           int(index_target),
            "stop_loss":        int(index_stop_loss),
            "gain_pct":         gain_pct,
            "risk_pct":         risk_pct,
            "confidence":       confidence,
            "rsi":              round(rsi, 1),
            "daily_rsi":        round(rsi, 1),
            "daily_trend":      "UP" if mom_5d > 0 else "DOWN",
            "macd_cross":       "macd_cross_bullish" in active_signals
                                or "macd_cross_bearish" in active_signals,
            "volume_spike":     vol_spike,
            "reason":           reason,
            "vix_str":          vix_str,
            "vix_level":        vix.get("level", "N/A"),
            "vix_current":      vix.get("current", 0),
            "sr_pivot":         sr.get("pivot", 0),
            "sr_r1":            sr.get("r1", 0),
            "sr_s1":            sr.get("s1", 0),
            "week_high":        sr.get("week_high", 0),
            "week_low":         sr.get("week_low", 0),
            "status":           "Open",
            "fo_option_type":   option_type,
            "fo_strike":        strike,
            "fo_expiry":        weekly_expiry,
            "fo_monthly_expiry": monthly_expiry,
            "fo_premium":       premiums["premium"],
            "fo_tgt_premium":   premiums["target_prem"],
            "fo_sl_premium":    premiums["sl_prem"],
            "fo_expected_move": premiums["expected_move"],
            "fo_lot_size":      config["lot_size"],
            "fo_days_to_expiry": days_to_expiry,
        }

    except Exception as e:
        print(f"[Index F&O] Error on {config['display']}: {e}")
        return None

def format_index_fo_message(sig: dict) -> str:
    """Format index F&O signal message with VIX and SR levels."""
    arrow      = "🟢" if sig["signal_type"] == "BUY" else "🔴"
    opt_arrow  = "📈" if sig["fo_option_type"] == "CE" else "📉"
    trend_icon = "⬆️" if sig.get("daily_trend") == "UP" else "⬇️"
    action     = "BUY CALL" if sig["signal_type"] == "BUY" else "BUY PUT"
    vix_str    = sig.get("vix_str", "")

    return (
        f"{arrow} <b>INDEX F&O — {sig['display_name']} "
        f"{sig['fo_strike']} {sig['fo_option_type']}</b>\n"
        f"{opt_arrow} <b>{action} SIGNAL</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Index levels</b>\n"
        f"  Current:    {sig['index_price']:,.0f}\n"
        f"  Target:     {sig['index_target']:,}  {trend_icon}  (+{sig.get('gain_pct',0)}%)\n"
        f"  Stop loss:  {sig['index_stop_loss']:,}  (-{sig.get('risk_pct',0)}%)\n\n"
        f"📐 <b>Key levels</b>\n"
        f"  Pivot:      {sig.get('sr_pivot', 'N/A')}\n"
        f"  Resistance: {sig.get('sr_r1', 'N/A')}\n"
        f"  Support:    {sig.get('sr_s1', 'N/A')}\n"
        f"  Week high:  {sig.get('week_high', 'N/A')}\n"
        f"  Week low:   {sig.get('week_low', 'N/A')}\n\n"
        f"🎯 <b>Option details</b>\n"
        f"  Strike:     {sig['fo_strike']} {sig['fo_option_type']}\n"
        f"  Expiry:     {sig['fo_expiry']} (weekly)\n"
        f"  Monthly:    {sig['fo_monthly_expiry']}\n"
        f"  Lot size:   {sig['fo_lot_size']} units\n\n"
        f"💰 <b>Premium targets</b>\n"
        f"  Buy at:     ₹{sig['fo_premium']}\n"
        f"  Target:     ₹{sig['fo_tgt_premium']}  "
        f"(+{round((sig['fo_tgt_premium']/sig['fo_premium']-1)*100)}%)\n"
        f"  Stop loss:  ₹{sig['fo_sl_premium']}  "
        f"(-{round((1-sig['fo_sl_premium']/sig['fo_premium'])*100)}%)\n"
        f"  Days left:  {sig['fo_days_to_expiry']} days\n"
        f"{vix_str}\n\n"
        f"💡 <b>Reason:</b> {sig['reason']}\n\n"
        f"⭐ Confidence: {sig['confidence']}%\n"
        f"⏰ {sig['date']} at {sig['time']}\n\n"
        f"⚠️ Index F&O is high risk. Not financial advice."
    )

def run_index_fo_scan() -> int:
    """
    Scan all 5 indices for F&O signals.
    Called inside intraday_signal_scan every 30 minutes.
    Returns count of index F&O signals sent.
    """
    print(f"\n  [Index F&O] Scanning {len(INDEX_CONFIG)} indices...")
    signals_sent = 0

    for symbol, config in INDEX_CONFIG.items():
        sig = detect_index_fo_signal(symbol, config)
        if sig:
            log_signal(sig)
            send_telegram(format_index_fo_message(sig))
            add_open_position(sig)          # ← track for monitoring
            signals_sent += 1
            print(f"  [Index F&O] Signal sent: {config['display']} "
                  f"{sig['fo_strike']} {sig['fo_option_type']} "
                  f"@ ₹{sig['fo_premium']} conf:{sig['confidence']}%")
            time.sleep(1.5)
        else:
            print(f"  [Index F&O] No signal: {config['display']}")

    return signals_sent


# ─────────────────────────────────────────────
#  PHASE 3 — END OF DAY SUMMARY
# ─────────────────────────────────────────────
def is_expiry_day(index_symbol: str) -> bool:
    """Return True if today is the expiry day for this index."""
    config = INDEX_CONFIG.get(index_symbol)
    if not config:
        return False
    return datetime.now(india).weekday() == config["expiry_weekday"]


def is_expiry_crunch_time() -> bool:
    """
    Return True if it is 1:00 PM – 3:15 PM AND today is any index expiry day.
    During this window options decay rapidly — scan every 5 minutes.
    """
    now    = datetime.now(india)
    h, m   = now.hour, now.minute
    in_window = (h == 13) or (h == 14) or (h == 15 and m <= 15)
    if not in_window:
        return False
    today_weekday = now.weekday()
    return any(
        cfg["expiry_weekday"] == today_weekday
        for cfg in INDEX_CONFIG.values()
    )


# ── Pre-market index scan ─────────────────────────────────────────
def premarket_index_scan():
    """
    Runs at 9:00 AM — before market opens.
    Blocked on weekends and NSE/BSE holidays.
    Uses previous day close + overnight cues for early signals.
    """
    # ── Holiday gate ──
    if is_market_holiday():
        holiday = get_holiday_name()
        print(f"[Pre-market] Holiday ({holiday}) — skipping index scan.")
        return

    print(f"\n[{datetime.now(india).strftime('%H:%M')}] PRE-MARKET INDEX SCAN")

    expiry_alerts = []
    for symbol, config in INDEX_CONFIG.items():
        if is_expiry_day(symbol):
            expiry_alerts.append(config["display"])

    expiry_note = ""
    if expiry_alerts:
        expiry_note = (
            f"\n⚠️ <b>Today is expiry day for:</b>\n"
            + "\n".join(f"  🔔 {name}" for name in expiry_alerts)
            + "\n5-min scans active 1:00 PM – 3:15 PM\n"
        )

    header = (
        f"🌅 <b>Pre-Market Index Report — "
        f"{datetime.now(india).strftime('%d %b %Y')}</b>\n"
        f"{expiry_note}\n"
        f"Scanning all 5 indices for opening signals...\n"
        f"Market opens at 9:15 AM"
    )
    send_telegram(header)

    signals_sent = 0
    for symbol, config in INDEX_CONFIG.items():
        try:
            # Use daily data for pre-market — no intraday yet
            df = fetch_stock_data(symbol, period="3mo", interval="1d")
            if df is None:
                continue
            df  = calculate_indicators(df)
            sig = detect_index_fo_signal(symbol, config)
            if sig:
                # Tag as pre-market signal
                sig["time"] = "Pre-market"
                log_signal(sig)
                msg = format_index_fo_message(sig)
                msg = msg.replace(
                    "⏰",
                    "🌅 <b>Pre-market signal — act at 9:15 AM open</b>\n⏰"
                )
                send_telegram(msg)
                signals_sent += 1
                time.sleep(1.5)
        except Exception as e:
            print(f"  [Pre-market] Error {config['display']}: {e}")

    if signals_sent == 0:
        print("[Pre-market] No signals found — live scanning starts at 9:15 AM.")
    print(f"[Pre-market] Done. {signals_sent} signals sent.")


# ── Dedicated live index F&O scan (every 15 min) ─────────────────
def live_index_fo_scan():
    """
    Runs every 15 minutes from 9:15 AM to 3:30 PM on trading days.
    Blocked on weekends and NSE/BSE holidays.
    """
    if is_market_holiday():
        return
    if not is_market_open():
        return

    now         = datetime.now(india)
    is_expiry   = is_expiry_crunch_time()
    mode_label  = "EXPIRY 5-MIN" if is_expiry else "15-MIN"

    print(f"\n[{now.strftime('%H:%M')}] INDEX F&O SCAN [{mode_label}]")

    signals_sent = 0
    expiry_day_indices = []

    for symbol, config in INDEX_CONFIG.items():
        # On expiry crunch — only scan the index that is expiring today
        if is_expiry and not is_expiry_day(symbol):
            continue

        if is_expiry_day(symbol):
            expiry_day_indices.append(config["display"])

        sig = detect_index_fo_signal(symbol, config)
        if sig:
            # Duplicate check — only send each index signal once per day
            idx_key = f"{sig['stock']}_{sig['signal_type']}_{sig.get('fo_strike','')}"
            if idx_key in _signals_sent_today:
                print(f"  Already sent today: {config['display']} — skipping")
                continue
            _signals_sent_today.add(idx_key)
            # Add expiry urgency note if expiry day
            if is_expiry_day(symbol):
                sig["reason"] += " | ⚠️ EXPIRY DAY — act quickly"
            log_signal(sig)
            send_telegram(format_index_fo_message(sig))
            add_open_position(sig)
            signals_sent += 1
            print(
                f"  Signal: {config['display']} "
                f"{sig['fo_strike']} {sig['fo_option_type']} "
                f"₹{sig['fo_premium']} conf:{sig['confidence']}%"
            )
            time.sleep(1.5)
        else:
            print(f"  No signal: {config['display']}")

    # No message when no signal found — only print to terminal
    if is_expiry and expiry_day_indices and signals_sent == 0:
        print(f"  [Expiry Crunch] No signal this scan — "
              f"monitoring {', '.join(expiry_day_indices)}. Next in 5 min.")

    print(f"[Index F&O] Scan done. {signals_sent} signals sent.")
    return signals_sent


# ── Expiry day 5-minute scanner ───────────────────────────────────
def expiry_5min_scan():
    """
    Runs every 5 minutes but only executes during expiry crunch time
    (1:00 PM – 3:15 PM on an expiry day). Blocked on holidays.
    """
    if is_market_holiday():
        return
    if not is_expiry_crunch_time():
        return
    if not is_market_open():
        return
    live_index_fo_scan()


# ── Index end-of-day summary ──────────────────────────────────────
def index_eod_summary():
    """
    Sends a dedicated index F&O end-of-day summary at 3:35 PM.
    Shows how each index closed and all signals from today.
    """
    print(f"\n[{datetime.now(india).strftime('%H:%M')}] INDEX EOD SUMMARY")

    lines = [f"📊 <b>Index F&O — End of Day</b>\n"
             f"📅 {date.today().strftime('%d %b %Y')}\n"]

    for symbol, config in INDEX_CONFIG.items():
        try:
            df = fetch_stock_data(symbol, period="5d", interval="1d")
            if df is None or df.empty:
                continue
            close     = float(df["Close"].iloc[-1])
            prev      = float(df["Close"].iloc[-2])
            change    = close - prev
            change_pct = (change / prev) * 100
            arrow     = "⬆️" if change >= 0 else "⬇️"
            expiry_tag = " 🔔 EXPIRY" if is_expiry_day(symbol) else ""
            lines.append(
                f"{arrow} <b>{config['display']}</b>{expiry_tag}\n"
                f"   Close: {close:,.0f}  "
                f"({'+' if change >= 0 else ''}{change_pct:.2f}%)\n"
            )
        except Exception as e:
            print(f"  [Index EOD] {config['display']}: {e}")

    # Count today's index signals from log
    if os.path.isfile(LOG_FILE):
        try:
            df_log = None
            for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
                try:
                    df_log = pd.read_csv(LOG_FILE, encoding=enc)
                    break
                except Exception:
                    continue
            if df_log is None:
                df_log = pd.DataFrame()
            today_str = date.today().strftime("%d-%m-%Y")
            idx_today = df_log[
                (df_log["date"] == today_str) &
                (df_log.get("signal_category", pd.Series()) == "INDEX_FO")
            ] if "signal_category" in df_log.columns else pd.DataFrame()
            lines.append(
                f"\n📈 Index F&O signals today: {len(idx_today)}\n"
                f"Update results in Google Sheet."
            )
        except Exception:
            pass

    send_telegram("\n".join(lines))
    print("[Index EOD] Summary sent.")


def end_of_day_summary():
    """Sends a daily summary at 4:00 PM."""
    print(f"\n[{datetime.now(india).strftime('%H:%M')}] Generating end of day summary...")

    if not os.path.isfile(LOG_FILE):
        send_telegram("📊 No signals logged today.")
        return

    # Encoding fallback chain — handles ₹ symbol and Windows chars
    df = None
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(LOG_FILE, encoding=enc)
            break
        except Exception:
            continue
    if df is None:
        send_telegram("📊 Could not read signals log today.")
        return
    today_str = date.today().strftime("%d-%m-%Y")
    today_df  = df[df["date"] == today_str]

    if today_df.empty:
        send_telegram(f"📊 No signals detected today ({today_str}).")
        return

    total    = len(today_df)
    buy_cnt  = len(today_df[today_df["signal_type"] == "BUY"])
    sell_cnt = len(today_df[today_df["signal_type"] == "SELL"])
    fo_cnt   = len(today_df[today_df.get("signal_category", "") == "F&O"]) if "signal_category" in today_df.columns else 0
    avg_conf = round(today_df["confidence"].mean(), 1)

    msg = (
        f"🌙 <b>End of Day Summary — {today_str}</b>\n\n"
        f"📊 Total signals:   {total}\n"
        f"🟢 Buy signals:     {buy_cnt}\n"
        f"🔴 Sell signals:    {sell_cnt}\n"
        f"📈 F&O signals:     {fo_cnt}\n"
        f"⭐ Avg confidence: {avg_conf}%\n\n"
        f"💾 All logged to signals_log.csv\n"
        f"📱 Update results in Google Sheet.\n\n"
        f"See you tomorrow at 9:00 AM!"
    )
    send_telegram(msg)
    print("[EOD] Summary sent.")


# ─────────────────────────────────────────────
#  SCHEDULER — RUNS EVERYTHING AUTOMATICALLY
# ─────────────────────────────────────────────
def run_scheduler():
    """
    Full schedule — stocks and index F&O on separate independent timers.

    STOCK SIGNALS
    ─────────────
    09:00 AM      Morning filter scan — all NSE+BSE stocks
    Every 30 min  Intraday stock signal scan (watchlist only)
    04:00 PM      End of day summary

    INDEX F&O SIGNALS (independent — never blocked by stock scan)
    ─────────────────
    09:00 AM      Pre-market index scan — early signals before open
    Every 15 min  Live index F&O scan  — 9:15 AM to 3:30 PM
    Every 5 min   Expiry crunch scan   — 1:00 PM to 3:15 PM on expiry days
    03:35 PM      Index end-of-day summary

    INDICES COVERED
    ───────────────
    NIFTY 50      — weekly expiry every Thursday
    BANK NIFTY    — weekly expiry every Wednesday
    SENSEX        — weekly expiry every Friday
    FIN NIFTY     — weekly expiry every Tuesday
    MIDCAP NIFTY  — weekly expiry every Monday
    """
    now_dt = datetime.now(india)

    print("\n" + "="*55)
    print("   STOCK + INDEX F&O SIGNAL ENGINE")
    print("="*55)
    print(f"   Date : {date.today().strftime('%d %b %Y')}")
    print(f"   Time : {now_dt.strftime('%I:%M %p')}")
    print("="*55)
    print("   STOCK SCHEDULE")
    print("   09:00 AM  — Morning scan (all NSE+BSE stocks)")
    print("   Every 30m — Intraday stock scan (watchlist)")
    print("   04:00 PM  — Stock end-of-day summary")
    print("─"*55)
    print("   HEARTBEAT")
    print("   Every 1hr — Telegram ping: engine alive + market status")
    print("─"*55)
    print("   INDEX F&O SCHEDULE")
    print("   09:00 AM  — Pre-market index scan")
    print("   Every 15m — Live index F&O scan")
    print("   Every 5m  — Expiry crunch (1–3:15 PM on expiry days)")
    print("   03:35 PM  — Index end-of-day summary")
    print("─"*55)
    print("   INDICES")
    print("   NIFTY 50     → expiry every Thursday")
    print("   BANK NIFTY   → expiry every Wednesday")
    print("   SENSEX       → expiry every Friday")
    print("   FIN NIFTY    → expiry every Tuesday")
    print("   MIDCAP NIFTY → expiry every Monday")
    print("="*55 + "\n")

    send_startup_message()

    # ── Heartbeat — every 60 minutes ────────────────
    # Sends a "engine alive" ping to Telegram every hour
    schedule.every(60).minutes.do(send_heartbeat)

    # ── Stock schedule ──────────────────────────────
    schedule.every().day.at("09:00").do(morning_filter_scan)
    schedule.every(30).minutes.do(intraday_signal_scan)
    schedule.every().day.at("16:00").do(end_of_day_summary)

    # ── Position monitor — every 15 min ─────────────
    # Checks all open positions for target hit or stop loss
    schedule.every(15).minutes.do(monitor_open_positions)

    # ── Index F&O schedule ──────────────────────────
    # Pre-market — 9:00 AM daily
    schedule.every().day.at("09:00").do(premarket_index_scan)

    # Live scan — every 15 minutes
    schedule.every(15).minutes.do(live_index_fo_scan)

    # Expiry crunch — every 5 minutes (function self-gates to 1–3:15 PM)
    schedule.every(5).minutes.do(expiry_5min_scan)

    # Index EOD — 3:35 PM daily
    schedule.every().day.at("15:35").do(index_eod_summary)

    # ── Immediate startup logic ─────────────────────
    now = datetime.now(india)
    h   = now.hour

    if is_market_holiday():
        holiday = get_holiday_name()
        print(f"\n[Startup] Today is a market holiday — {holiday}")
        print("[Startup] Engine running but all scans are blocked today.")
        print("[Startup] Scans resume automatically next trading day.\n")
    elif 9 <= h < 16:
        print("[Startup] Market hours — running morning stock scan now...")
        morning_filter_scan()

        print("[Startup] Running first live index scan now...")
        live_index_fo_scan()

        print("[Startup] Checking open positions from previous signals...")
        monitor_open_positions()

        if is_expiry_crunch_time():
            print("[Startup] Expiry crunch detected — running 5-min scan...")
            expiry_5min_scan()
    else:
        print(f"[Startup] Outside market hours ({now.strftime('%I:%M %p')}) — waiting for 9:00 AM.")

    # ── Keep running ────────────────────────────────
    print("\n[Engine] Running. Press Ctrl+C to stop.\n")
    print("[Engine] Internet watchdog active — auto-reconnect enabled.\n")
    tick = 0
    while True:
        schedule.run_pending()
        time.sleep(30)
        tick += 1
        # Check internet every 60 seconds (every 2 ticks)
        if tick % 2 == 0:
            check_internet_and_flush()


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    run_scheduler()