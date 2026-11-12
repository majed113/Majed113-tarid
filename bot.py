import os
import time
import sqlite3
import logging
import asyncio
from datetime import datetime, timezone

import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ---------------- SETTINGS: PAPER TRADING ONLY ----------------
BASE_URL = "https://api.ourbit.com"
WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
INTERVAL = "5m"
SCAN_SECONDS = 60

START_BALANCE = 100.0
POSITION_USDT = 25.0
MAX_OPEN_TRADES = 2
STOP_LOSS_PCT = 0.015       # 1.5%
TAKE_PROFIT_PCT = 0.025     # 2.5%
FEE_RATE = 0.001            # estimated 0.1% per side; adjust if needed
MAX_DAILY_LOSS_USDT = 3.0

DB_FILE = "paper_trading.db"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("majed-paper-bot")


# ---------------- DATABASE ----------------
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id=1),
                balance REAL NOT NULL
            )
        """)
        con.execute("""
            INSERT OR IGNORE INTO settings(id, balance) VALUES(1, ?)
        """, (START_BALANCE,))
        con.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry REAL NOT NULL,
                qty REAL NOT NULL,
                invested REAL NOT NULL,
                stop REAL NOT NULL,
                target REAL NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                exit REAL,
                pnl REAL,
                status TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY
            )
        """)


def get_balance():
    with db() as con:
        return float(con.execute(
            "SELECT balance FROM settings WHERE id=1"
        ).fetchone()["balance"])


def set_balance(value):
    with db() as con:
        con.execute("UPDATE settings SET balance=? WHERE id=1", (value,))


def open_trades():
    with db() as con:
        return con.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY id"
        ).fetchall()


def add_user(chat_id):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO users(chat_id) VALUES(?)", (chat_id,))


def get_users():
    with db() as con:
        return [r["chat_id"] for r in con.execute("SELECT chat_id FROM users")]


def daily_realized_loss():
    today = datetime.now(timezone.utc).date().isoformat()
    with db() as con:
        row = con.execute("""
            SELECT COALESCE(SUM(CASE WHEN pnl < 0 THEN -pnl ELSE 0 END), 0) AS loss
            FROM trades
            WHERE status='CLOSED' AND substr(closed_at,1,10)=?
        """, (today,)).fetchone()
    return float(row["loss"])


def save_trade(symbol, entry):
    qty = POSITION_USDT / entry
    stop = entry * (1 - STOP_LOSS_PCT)
    target = entry * (1 + TAKE_PROFIT_PCT)
    with db() as con:
        row = con.execute(
            "SELECT balance FROM settings WHERE id=1"
        ).fetchone()
        balance = float(row["balance"])
        if balance < POSITION_USDT:
            return False
        con.execute("UPDATE settings SET balance=? WHERE id=1",
                    (balance - POSITION_USDT,))
        con.execute("""
            INSERT INTO trades(symbol,entry,qty,invested,stop,target,opened_at,status)
            VALUES(?,?,?,?,?,?,?,'OPEN')
        """, (
            symbol, entry, qty, POSITION_USDT, stop, target,
            datetime.now(timezone.utc).isoformat()
        ))
    return True


def close_trade(trade_id, exit_price):
    with db() as con:
        trade = con.execute(
            "SELECT * FROM trades WHERE id=? AND status='OPEN'",
            (trade_id,)
        ).fetchone()
        if not trade:
            return None
        gross = (exit_price - trade["entry"]) * trade["qty"]
        fees = (trade["entry"] * trade["qty"] + exit_price * trade["qty"]) * FEE_RATE
        pnl = gross - fees
        balance = float(con.execute(
            "SELECT balance FROM settings WHERE id=1"
        ).fetchone()["balance"])
        # Return invested capital plus net profit/loss to simulated cash balance.
        balance += float(trade["invested"]) + pnl
        con.execute("UPDATE settings SET balance=? WHERE id=1", (balance,))
        con.execute("""
            UPDATE trades SET status='CLOSED',closed_at=?,exit=?,pnl=?
            WHERE id=?
        """, (datetime.now(timezone.utc).isoformat(), exit_price, pnl, trade_id))
        return {"symbol": trade["symbol"], "pnl": pnl, "exit": exit_price}


# ---------------- OURBIT PUBLIC MARKET DATA ----------------
def api_get(path, params=None):
    response = requests.get(
        BASE_URL + path, params=params, timeout=15,
        headers={"User-Agent": "MajedCryptoTrader-Paper/1.0"}
    )
    response.raise_for_status()
    return response.json()


def get_price(symbol):
    data = api_get("/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"])


def get_closes(symbol):
    # Ourbit returns candles as arrays; use only completed candles.
    rows = api_get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": INTERVAL, "limit": 60}
    )
    if not isinstance(rows, list) or len(rows) < 30:
        raise ValueError(f"Not enough candle data for {symbol}")
    completed = rows[:-1]
    return [float(row[4]) for row in completed]


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * alpha + result * (1 - alpha)
    return result


def rsi(values, period=14):
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes[-period:]]
    losses = [max(-x, 0) for x in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_signal(symbol):
    closes = get_closes(symbol)
    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)
    strength = rsi(closes, 14)
    price = get_price(symbol)

    # Conservative trend-following entry filter; not a profit guarantee.
    if fast > slow and price > slow and 50 <= strength <= 68:
        return {"symbol": symbol, "price": price, "rsi": strength,
                "ema_fast": fast, "ema_slow": slow}
    return None


# ---------------- PAPER ENGINE ----------------
async def scan_market(app):
    try:
        # First manage existing virtual positions.
        for trade in open_trades():
            try:
                price = await asyncio.to_thread(get_price, trade["symbol"])
                if price <= trade["stop"] or price >= trade["target"]:
                    result = close_trade(trade["id"], price)
                    if result:
                        msg = (
                            f"🔔 معامله مجازی بسته شد\n"
                            f"ارز: {result['symbol']}\n"
                            f"قیمت خروج: {result['exit']:.8g}\n"
                            f"سود/زیان خالص: {result['pnl']:.4f} USDT"
                        )
                        for chat_id in get_users():
                            await app.bot.send_message(chat_id, msg)
            except Exception:
                log.exception("Could not manage trade %s", trade["id"])

        # Daily stop: do not open new positions after the loss limit.
        if daily_realized_loss() >= MAX_DAILY_LOSS_USDT:
            return

        current = open_trades()
        if len(current) >= MAX_OPEN_TRADES:
            return

        already_open = {t["symbol"] for t in current}
        for symbol in WATCHLIST:
            if len(open_trades()) >= MAX_OPEN_TRADES:
                break
            if symbol in already_open:
                continue
            try:
                signal = await asyncio.to_thread(get_signal, symbol)
                if signal:
                    balance = get_balance()
                    if balance < POSITION_USDT:
                        return
                    if not save_trade(symbol, signal["price"]):
                        return
                    already_open.add(symbol)
                    msg = (
                        f"🟢 خرید مجازی ثبت شد\n"
                        f"ارز: {symbol}\n"
                        f"قیمت ورود: {signal['price']:.8g}\n"
                        f"حجم: {POSITION_USDT:.2f} USDT\n"
                        f"حد ضرر: {signal['price'] * (1-STOP_LOSS_PCT):.8g}\n"
                        f"حد سود: {signal['price'] * (1+TAKE_PROFIT_PCT):.8g}\n"
                        f"RSI: {signal['rsi']:.1f}\n"
                        f"حالت: فقط آزمایشی"
                    )
                    for chat_id in get_users():
                        await app.bot.send_message(chat_id, msg)
            except Exception:
                log.exception("Scan failed for %s", symbol)
    except Exception:
        log.exception("Market scan failed")


async def scanner_loop(app):
    while True:
        await scan_market(app)
        await asyncio.sleep(SCAN_SECONDS)


async def post_init(app):
    init_db()
    app.bot_data["scanner_task"] = asyncio.create_task(scanner_loop(app))
    log.info("Paper trading scanner started")


async def post_shutdown(app):
    task = app.bot_data.get("scanner_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------- TELEGRAM COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_chat.id)
    await update.message.reply_text(
        "سلام! 🤖 Majed Crypto Trader آماده است.\n"
        "اتصال: قیمت‌های عمومی Ourbit\n"
        "بازار: Spot | حالت: Paper Trading\n\n"
        "/status - وضعیت و موجودی\n"
        "/scan - بررسی فوری بازار\n"
        "/trades - معاملات باز\n"
        "/report - گزارش عملکرد\n"
        "/help - راهنما\n\n"
        "هیچ سفارش واقعی ارسال نمی‌شود."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_chat.id)
    try:
        ping = await asyncio.to_thread(api_get, "/api/v3/ping")
        message = (
            "وضعیت ربات: فعال ✅\n"
            f"اتصال عمومی Ourbit: برقرار ✅ ({ping})\n"
            f"موجودی نقد مجازی: {get_balance():.2f} USDT\n"
            f"معاملات باز: {len(open_trades())}\n"
            "حالت: آزمایشی؛ سفارش واقعی غیرفعال"
        )
    except Exception as exc:
        message = f"ربات فعال است، اما دریافت داده از Ourbit خطا دارد:\n{exc}"
    await update.message.reply_text(message)


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_chat.id)
    await update.message.reply_text("در حال بررسی قیمت‌ها و کندل‌های Ourbit...")
    await scan_market(context.application)
    await update.message.reply_text(
        "بررسی تمام شد. اگر شرط ورود برقرار باشد، پیام معامله مجازی ارسال می‌شود."
    )


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = open_trades()
    if not rows:
        await update.message.reply_text("در حال حاضر معامله مجازی بازی وجود ندارد.")
        return
    lines = ["📊 معاملات مجازی باز:"]
    for t in rows:
        lines.append(
            f"{t['symbol']} | ورود {t['entry']:.8g} | "
            f"حدضرر {t['stop']:.8g} | حدسود {t['target']:.8g}"
        )
    await update.message.reply_text("\n".join(lines))


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as con:
        closed = con.execute(
            "SELECT COUNT(*) AS n, "
            "COALESCE(SUM(pnl),0) AS pnl, "
            "COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0) AS wins "
            "FROM trades WHERE status='CLOSED'"
        ).fetchone()
    n = int(closed["n"])
    wins = int(closed["wins"])
    win_rate = (wins / n * 100) if n else 0
    await update.message.reply_text(
        "📈 گزارش معاملات آزمایشی\n"
        f"موجودی نقد مجازی: {get_balance():.2f} USDT\n"
        f"معاملات بسته‌شده: {n}\n"
        f"معاملات سودده: {wins}\n"
        f"درصد برد: {win_rate:.1f}%\n"
        f"سود/زیان خالص ثبت‌شده: {float(closed['pnl']):.4f} USDT\n"
        f"معاملات باز: {len(open_trades())}\n"
        f"زیان تحقق‌یافته امروز: {daily_realized_loss():.4f} USDT\n"
        "توجه: این گزارش شبیه‌سازی است و لغزش قیمت/کارمزد واقعی ممکن است متفاوت باشد."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - شروع و ثبت دریافت اعلان‌ها\n"
        "/status - اتصال و وضعیت\n"
        "/scan - اسکن فوری\n"
        "/trades - معاملات مجازی باز\n"
        "/report - گزارش سود و زیان\n\n"
        "ربات فقط قیمت عمومی را می‌خواند و معامله‌ها را در پایگاه داده محلی شبیه‌سازی می‌کند."
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    init_db()
    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("trades", trades))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("help", help_command))

    log.info("Majed Crypto Trader: PAPER TRADING ONLY")
    app.run_polling()


if __name__ == "__main__":
    main()
