"""
ForexPulse Bot — Live Forex Rates, Pip Calculator & Price Alerts
A data-only Telegram bot. No signals, no trade calls, no financial advice.
Data source: Frankfurter API (frankfurter.dev) - free, ECB-backed, no key required.
"""

import os
import sqlite3
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_FILE = "forexpulse.db"
FX_BASE = "https://api.frankfurter.dev/v1"
CHECK_INTERVAL_SECONDS = 60

# Major + common pairs we validate against (ISO 4217 codes)
VALID_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNY",
    "SEK", "NOK", "MXN", "SGD", "HKD", "ZAR", "TRY", "INR", "BRL",
    "PLN", "DKK", "THB", "IDR", "KRW", "AED", "SAR", "NGN"
}

# Standard pip size lookup: most pairs = 0.0001, JPY pairs = 0.01
def pip_size(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("forexpulse")

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            base TEXT NOT NULL,
            quote TEXT NOT NULL,
            target_rate REAL NOT NULL,
            direction TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def add_alert(chat_id, base, quote, target_rate, direction):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO alerts (chat_id, base, quote, target_rate, direction, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, base, quote, target_rate, direction, datetime.utcnow().isoformat()),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def get_alerts_for_chat(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, base, quote, target_rate, direction FROM alerts WHERE chat_id = ?", (chat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_alert(chat_id, alert_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM alerts WHERE chat_id = ? AND id = ?", (chat_id, alert_id))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def get_all_alerts():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, base, quote, target_rate, direction FROM alerts")
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# FX HELPERS
# ---------------------------------------------------------------------------
def parse_pair(pair_input):
    """Turn 'eurusd' or 'EUR/USD' or 'eur usd' into ('EUR', 'USD'), or (None, None) if invalid."""
    cleaned = pair_input.upper().replace("/", "").replace("-", "").replace(" ", "")
    if len(cleaned) != 6:
        return None, None
    base, quote = cleaned[:3], cleaned[3:]
    if base not in VALID_CURRENCIES or quote not in VALID_CURRENCIES:
        return None, None
    return base, quote


def fetch_rate(base, quote):
    resp = requests.get(f"{FX_BASE}/latest", params={"base": base, "symbols": quote}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("rates", {}).get(quote)


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        payload = context.args[0]
        parts = payload.split("_")
        if len(parts) == 3:
            pair_str, price_str, direction = parts
            direction = direction.lower()
            base, quote = parse_pair(pair_str)
            if base and direction in ("above", "below"):
                try:
                    target_rate = float(price_str)
                    chat_id = update.effective_chat.id
                    alert_id = add_alert(chat_id, base, quote, target_rate, direction)
                    await update.message.reply_markdown(
                        f"👋 *Welcome to ForexPulse!*\n\n"
                        f"✅ Alert #{alert_id} set from the Mini App: *{base}/{quote}* {direction} {target_rate}\n"
                        f"I'll message you the moment it crosses.\n\n"
                        f"Type /help to see everything else I can do."
                    )
                    return
                except ValueError:
                    pass

    text = (
        "👋 *Welcome to ForexPulse!*\n\n"
        "Live exchange rates, pip calculations, and price alerts — no signup, "
        "no broker connection.\n\n"
        "Try:\n"
        "`/rate EURUSD`\n"
        "`/pip EURUSD 1`\n"
        "`/alert GBPUSD 1.30 above`\n\n"
        "Type /help to see everything I can do."
    )
    await update.message.reply_markdown(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*ForexPulse Commands*\n\n"
        "/rate `<pair>` — get the live exchange rate\n"
        "  _example:_ `/rate EURUSD`\n\n"
        "/convert `<amount> <from> <to>` — convert between currencies\n"
        "  _example:_ `/convert 100 USD EUR`\n\n"
        "/pip `<pair> <lot_size>` — calculate pip value\n"
        "  _example:_ `/pip EURUSD 1`\n\n"
        "/alert `<pair> <rate> <above|below>` — get notified when a rate crosses your target\n"
        "  _example:_ `/alert GBPUSD 1.30 above`\n\n"
        "/alerts — list your active alerts\n\n"
        "/delalert `<id>` — remove an alert by its ID\n\n"
        "/about — what this bot does and doesn't do\n\n"
        "_Rates are provided by the Frankfurter/ECB public API. This bot does not "
        "provide trade signals or financial advice._"
    )
    await update.message.reply_markdown(text)


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*About ForexPulse*\n\n"
        "ForexPulse is a free tool for tracking exchange rates and setting price "
        "alerts. It does not connect to any broker or trading account.\n\n"
        "📊 This is a data and calculation tool — not financial advice, not a "
        "signal service, and not a trading platform.\n"
        "🔒 We never ask for broker logins, account numbers, or funds.\n"
        "🧑‍💻 Built and maintained independently."
    )
    await update.message.reply_markdown(text)


async def rate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rate <pair>\nExample: /rate EURUSD")
        return

    base, quote = parse_pair(context.args[0])
    if not base:
        await update.message.reply_text("❌ Invalid pair. Use format like EURUSD or EUR/USD.")
        return

    await update.message.reply_chat_action("typing")

    try:
        rate = fetch_rate(base, quote)
    except Exception as e:
        logger.error(f"Rate fetch failed: {e}")
        await update.message.reply_text("⚠️ Couldn't fetch the rate right now. Try again shortly.")
        return

    if rate is None:
        await update.message.reply_text("⚠️ No rate data found for that pair.")
        return

    await update.message.reply_markdown(f"*{base}/{quote}* — {rate:.5f}")


async def convert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /convert <amount> <from> <to>\nExample: /convert 100 USD EUR")
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number.")
        return

    base = context.args[1].upper()
    quote = context.args[2].upper()

    if base not in VALID_CURRENCIES or quote not in VALID_CURRENCIES:
        await update.message.reply_text("❌ Unrecognized currency code. Use ISO codes like USD, EUR, GBP.")
        return

    await update.message.reply_chat_action("typing")

    try:
        rate = fetch_rate(base, quote)
    except Exception as e:
        logger.error(f"Convert fetch failed: {e}")
        await update.message.reply_text("⚠️ Couldn't fetch the rate right now. Try again shortly.")
        return

    if rate is None:
        await update.message.reply_text("⚠️ No rate data found for that pair.")
        return

    result = amount * rate
    await update.message.reply_markdown(
        f"*{amount:,.2f} {base}* = *{result:,.2f} {quote}*\n_Rate: 1 {base} = {rate:.5f} {quote}_"
    )


async def pip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /pip <pair> <lot_size>\nExample: /pip EURUSD 1\n(1 standard lot = 100,000 units)"
        )
        return

    base, quote = parse_pair(context.args[0])
    if not base:
        await update.message.reply_text("❌ Invalid pair. Use format like EURUSD.")
        return

    try:
        lot_size = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Lot size must be a number, e.g. 1 or 0.1")
        return

    await update.message.reply_chat_action("typing")

    units = lot_size * 100000
    size = pip_size(f"{base}{quote}")

    # pip value in quote currency terms
    pip_value_quote = units * size

    # convert to USD if quote isn't already USD, for a friendlier reference number
    usd_note = ""
    if quote != "USD":
        try:
            rate_to_usd = fetch_rate(quote, "USD")
            if rate_to_usd:
                pip_value_usd = pip_value_quote * rate_to_usd
                usd_note = f" (~{pip_value_usd:.2f} USD)"
        except Exception:
            pass

    await update.message.reply_markdown(
        f"*{base}/{quote}* — {lot_size} lot ({units:,.0f} units)\n"
        f"Pip value: *{pip_value_quote:.2f} {quote}*{usd_note}"
    )


async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /alert <pair> <rate> <above|below>\nExample: /alert GBPUSD 1.30 above"
        )
        return

    base, quote = parse_pair(context.args[0])
    if not base:
        await update.message.reply_text("❌ Invalid pair. Use format like EURUSD.")
        return

    direction = context.args[2].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("Direction must be 'above' or 'below'.")
        return

    try:
        target_rate = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Rate must be a number, e.g. 1.30")
        return

    chat_id = update.effective_chat.id
    alert_id = add_alert(chat_id, base, quote, target_rate, direction)

    await update.message.reply_markdown(
        f"✅ Alert #{alert_id} set: *{base}/{quote}* {direction} {target_rate}\n"
        f"I'll message you the moment it crosses."
    )


async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = get_alerts_for_chat(chat_id)
    if not rows:
        await update.message.reply_text("You have no active alerts. Set one with /alert <pair> <rate> <above|below>")
        return

    lines = ["*Your Active Alerts*\n"]
    for alert_id, base, quote, target_rate, direction in rows:
        lines.append(f"#{alert_id} — {base}/{quote} {direction} {target_rate}")
    lines.append("\nRemove one with /delalert <id>")
    await update.message.reply_markdown("\n".join(lines))


async def delalert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delalert <id>")
        return
    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Alert ID must be a number. Check /alerts for your IDs.")
        return

    chat_id = update.effective_chat.id
    deleted = delete_alert(chat_id, alert_id)
    if deleted:
        await update.message.reply_text(f"🗑️ Alert #{alert_id} removed.")
    else:
        await update.message.reply_text("Couldn't find that alert ID under your account.")


# ---------------------------------------------------------------------------
# BACKGROUND JOB
# ---------------------------------------------------------------------------
async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    rows = get_all_alerts()
    if not rows:
        return

    pairs = list({(r[2], r[3]) for r in rows})
    rates = {}
    for base, quote in pairs:
        try:
            rate = fetch_rate(base, quote)
            if rate is not None:
                rates[(base, quote)] = rate
        except Exception as e:
            logger.error(f"Alert check fetch failed for {base}/{quote}: {e}")

    for alert_id, chat_id, base, quote, target_rate, direction in rows:
        current = rates.get((base, quote))
        if current is None:
            continue

        triggered = (direction == "above" and current >= target_rate) or (
            direction == "below" and current <= target_rate
        )

        if triggered:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔔 *Alert Triggered!*\n"
                        f"{base}/{quote} is now {current:.5f} ({direction} your target of {target_rate})"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            delete_alert(chat_id, alert_id)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CommandHandler("rate", rate_cmd))
    app.add_handler(CommandHandler("convert", convert_cmd))
    app.add_handler(CommandHandler("pip", pip_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", alerts_cmd))
    app.add_handler(CommandHandler("delalert", delalert_cmd))

    app.job_queue.run_repeating(check_alerts_job, interval=CHECK_INTERVAL_SECONDS, first=10)

    logger.info("ForexPulse bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
