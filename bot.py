
import os
import json
import time
import asyncio
import requests

from datetime import datetime, timezone
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# =====================================
# SETTINGS
# =====================================

API = "https://api.ourbit.com/api/v3"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

START_BALANCE = 100.0
RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.06
MAX_POSITION_SIZE = 40.0
MAX_OPEN_TRADES = 3

FEE_RATE = 0.002  # فرض کارمزد 0.2 درصد در هر سمت
MIN_TRADE_SIZE = 5.0
SCAN_INTERVAL = 60

STATE_FILE = "paper_state.json"

# سفارش واقعی همیشه خاموش است
REAL_ORDERS_ENABLED = False


# =====================================
# STATE
# =====================================

def new_state():
    return {
        "cash": START_BALANCE,
        "paper_enabled": False,
        "open_trades": [],
        "history": [],
        "closed_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_realized_pnl": 0.0,
        "peak_equity": START_BALANCE,
        "max_drawdown": 0.0,
        "daily_date": datetime.now(timezone.utc).date().isoformat(),
        "daily_start_equity": START_BALANCE
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)

            if isinstance(state, dict) and "cash" in state:
                return state

        except Exception as error:
            print("State load error:", error)

    return new_state()


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(temp_file, STATE_FILE)


# =====================================
# MARKET DATA
# =====================================

def get_json(path, params=None):
    response = requests.get(
        API + path,
        params=params,
        timeout=15
    )
    response.raise_for_status()
    return response.json()


def get_klines(symbol, interval, limit=100):
    data = get_json(
        "/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    now_ms = int(time.time() * 1000)
    candles = []

    for item in data:
        try:
            candle = {
                "time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time": int(item[6])
            }

            # فقط کندل بسته‌شده
            if candle["close_time"] < now_ms:
                candles.append(candle)

        except (ValueError, TypeError, IndexError):
            continue

    return candles


def get_price(symbol):
    data = get_json(
        "/ticker/price",
        {"symbol": symbol}
    )

    return float(data["price"])


def get_snapshot(symbol):
    candles5 = get_klines(symbol, "5m", 100)
    candles15 = get_klines(symbol, "15m", 100)
    price = get_price(symbol)

    if len(candles5) < 55 or len(candles15) < 55:
        raise ValueError("Not enough closed candles")

    return {
        "price": price,
        "candles5": candles5,
        "candles15": candles15
    }


# =====================================
# INDICATORS
# =====================================

def ema(values, period):
    if len(values) < period:
        return []

    result = []
    current = sum(values[:period]) / period
    result.append(current)

    multiplier = 2 / (period + 1)

    for value in values[period:]:
        current = (
            value * multiplier
            + current * (1 - multiplier)
        )
        result.append(current)

    return result


def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    recent = changes[-period:]

    gains = [
        max(change, 0)
        for change in recent
    ]

    losses = [
        abs(min(change, 0))
        for change in recent
    ]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        ranges.append(true_range)

    return sum(ranges[-period:]) / period


# =====================================
# TRADING SIGNAL
# =====================================


def analyze(snapshot):
    candles5 = snapshot["candles5"]
    candles15 = snapshot["candles15"]
    price = snapshot["price"]

    closes5 = [c["close"] for c in candles5]
    closes15 = [c["close"] for c in candles15]

    ema20_15 = ema(closes15, 20)
    ema50_15 = ema(closes15, 50)

    ema9_5 = ema(closes5, 9)
    ema21_5 = ema(closes5, 21)

    rsi = calculate_rsi(closes5)
    atr = calculate_atr(candles5)

    if not all([ema20_15, ema50_15, ema9_5, ema21_5, atr]):
        return None

    trend_up = ema20_15[-1] > ema50_15[-1]

    entry_confirmed = (
        ema9_5[-1] > ema21_5[-1]
        and closes5[-1] > ema9_5[-1]
        and rsi is not None
        and 50 <= rsi <= 68
    )

    if not trend_up or not entry_confirmed:
        return None

    stop_distance = max(atr * 1.5, price * 0.005)

    if stop_distance / price > 0.03:
        return None

    stop = price - stop_distance

    return {
        "price": price,
        "stop": stop,
        "rsi": rsi,
        "atr": atr,
        "candle_time": candles5[-1]["time"]
    }


# =====================================
# ACCOUNT
# =====================================

def equity_value(state, prices):
    equity = state["cash"]

    for trade in state["open_trades"]:
        price = prices.get(
            trade["symbol"],
            trade["entry"]
        )

        equity += trade["remaining_qty"] * price

    return equity


def update_daily(state, prices):
    today = datetime.now(timezone.utc).date().isoformat()

    equity = equity_value(state, prices)

    if state["daily_date"] != today:
        state["daily_date"] = today
        state["daily_start_equity"] = equity

    peak = max(state["peak_equity"], equity)
    state["peak_equity"] = peak

    if peak > 0:
        drawdown = (peak - equity) / peak
        state["max_drawdown"] = max(
            state["max_drawdown"],
            drawdown
        )

    save_state(state)

    daily_loss = (
        state["daily_start_equity"] - equity
    )

    return daily_loss >= (
        state["daily_start_equity"] * MAX_DAILY_LOSS
    )


# =====================================
# OPEN PAPER TRADE
# =====================================


def open_trade(state, symbol, signal):



# =====================================
# CLOSE PART OF A TRADE
# =====================================

def close_quantity(state, trade, quantity, price, reason):
    quantity = min(
        quantity,
        trade["remaining_qty"]
    )

    if quantity <= 0:
        return

    fraction = quantity / trade["remaining_qty"]

    allocated_cost = (
        trade["remaining_cost"] * fraction
    )

    proceeds = quantity * price
    exit_fee = proceeds * FEE_RATE

    pnl = proceeds - exit_fee - allocated_cost

    state["cash"] += proceeds - exit_fee
    state["total_realized_pnl"] += pnl

    trade["remaining_qty"] -= quantity
    trade["remaining_cost"] -= allocated_cost
    trade["realized_pnl"] += pnl

    state["history"].append({
        "symbol": trade["symbol"],
        "reason": reason,
        "price": price,
        "pnl": pnl,
        "time": datetime.now(timezone.utc).isoformat()
    })

    if trade["remaining_qty"] <= trade["original_qty"] * 0.000001:
        state["closed_trades"] += 1

        if trade["realized_pnl"] > 0:
            state["wins"] += 1
        else:
            state["losses"] += 1

        state["open_trades"].remove(trade)

    save_state(state)


# =====================================
# MANAGE OPEN TRADES
# =====================================


def manage_trade(state, trade, snapshot):
    price = snapshot["price"]
    candle = snapshot["candles5"][-1]

    # کندل ورود نباید برای حد ضرر و حد سود بررسی شود
    if candle["time"] <= trade.get("last_managed_candle", 0):
        return

    trade["last_managed_candle"] = candle["time"]

    low = candle["low"]
    high = candle["high"]

    if low <= trade["stop"]:
        close_quantity(
            state,
            trade,
            trade["remaining_qty"],
            trade["stop"],
            "STOP LOSS"
        )
        return

    targets = [
        ("TP1", trade["target1"]),
        ("TP2", trade["target2"]),
        ("TP3", trade["target3"])
    ]

    for name, target in targets:
        if name in trade["targets_hit"]:
            continue

        if high >= target:
            quantity = min(
                trade["original_qty"] / 3,
                trade["remaining_qty"]
            )

            close_quantity(
                state,
                trade,
                quantity,
                target,
                name
            )

            trade["targets_hit"].append(name)

            if name == "TP1" and trade in state["open_trades"]:
                trade["stop"] = max(
                    trade["stop"],
                    trade["entry"]
                )

            if name == "TP2" and trade in state["open_trades"]:
                trade["stop"] = max(
                    trade["stop"],
                    trade["target1"]
                )

            save_state(state)

            if trade not in state["open_trades"]:
                return



# =====================================
# BACKGROUND PAPER ENGINE
# =====================================

async def paper_engine(app):
    print("Paper engine started")

    while True:
        try:
            state = load_state()
            prices = {}

            snapshots = {}

            for symbol in SYMBOLS:
                try:
                    snapshot = await asyncio.to_thread(
                        get_snapshot,
                        symbol
                    )

                    snapshots[symbol] = snapshot
                    prices[symbol] = snapshot["price"]

                except Exception as error:
                    print(symbol, "market error:", error)

            # مدیریت معاملات باز حتی پس از paper_off
            for trade in state["open_trades"][:]:
                snapshot = snapshots.get(trade["symbol"])

                if snapshot:
                    manage_trade(
                        state,
                        trade,
                        snapshot
                    )

            daily_limit_reached = update_daily(
                state,
                prices
            )

            # فقط وقتی روشن باشد، معامله جدید باز می‌کند
            if state["paper_enabled"] and not daily_limit_reached:

                for symbol, snapshot in snapshots.items():

                    signal = analyze(snapshot)

                    if signal:
                        opened = open_trade(
                            state,
                            symbol,
                            signal
                        )

                        if opened:
                            print(
                                "Paper trade opened:",
                                symbol,
                                signal["price"]
                            )

            save_state(state)

        except Exception as error:
            print("Paper engine error:", error)

        await asyncio.sleep(SCAN_INTERVAL)


# =====================================
# TELEGRAM COMMANDS
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 🤖\n"
        "Majed Crypto Trader آماده است.\n\n"
        "حالت: Aggressive Paper Trading\n"
        "بازار: Spot | صرافی: Ourbit\n\n"
        "/status - وضعیت\n"
        "/balance - موجودی\n"
        "/risk - تنظیمات ریسک\n"
        "/scan - بررسی بازار\n"
        "/paper_on - شروع معاملات آزمایشی\n"
        "/paper_off - توقف ورودهای جدید\n"
        "/trades - معاملات باز\n"
        "/report - گزارش عملکرد\n"
        "/help - راهنما\n\n"
        "سفارش واقعی غیرفعال است."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()

    mode = (
        "روشن ✅"
        if state["paper_enabled"]
        else "خاموش ⏸"
    )

    await update.message.reply_text(
        f"وضعیت ربات: فعال ✅\n"
        f"موتور آزمایشی: {mode}\n"
        f"صرافی: Ourbit\n"
        f"بازار: Spot\n"
        f"ارزها: BTC و ETH\n"
        f"سفارش واقعی: غیرفعال 🔒"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()

    prices = {}

    for trade in state["open_trades"]:
        try:
            prices[trade["symbol"]] = await asyncio.to_thread(
                get_price,
                trade["symbol"]
            )
        except Exception:
            prices[trade["symbol"]] = trade["entry"]

    equity = equity_value(state, prices)

    await update.message.reply_text(
        f"موجودی نقدی: {state['cash']:.2f} USDT\n"
        f"ارزش کل حساب: {equity:.2f} USDT\n"
        f"سود و زیان کل حساب: "
        f"{equity - START_BALANCE:+.2f} USDT"
    )


async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "تنظیمات حالت تهاجمی 🔥\n\n"
        "ریسک هر معامله: 2٪\n"
        "حداکثر ضرر روزانه: 6٪\n"
        "حداکثر حجم هر معامله: 40 USDT\n"
        "حداکثر معاملات هم‌زمان: 3\n"
        "اهرم: صفر\n"
        "حد ضرر: الزامی\n"
        "حد سود: سه مرحله‌ای\n"
        "کارمزد فرضی: 0.2٪ در هر سمت\n"
        "حالت: Paper Trading"
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text(
        "🔎 در حال بررسی بازار..."
    )

    try:
        result = "📊 بازار Ourbit\n\n"

        for symbol in SYMBOLS:
            price = await asyncio.to_thread(
                get_price,
                symbol
            )

            result += (
                f"{symbol}: {price:.8g} USDT\n"
            )

        await message.edit_text(result)

    except Exception as error:
        print("Scan error:", error)

        await message.edit_text(
            "خطا در دریافت قیمت بازار."
        )


async def paper_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["paper_enabled"] = True
    save_state(state)

    await update.message.reply_text(
        "🚀 موتور معاملات آزمایشی روشن شد.\n"
        "ربات بازار BTC و ETH را بررسی می‌کند.\n"
        "فقط معاملات شبیه‌سازی می‌شوند."
    )


async def paper_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["paper_enabled"] = False
    save_state(state)

    await update.message.reply_text(
        "⏸ ورود به معاملات جدید متوقف شد.\n"
        "معاملات باز همچنان مدیریت می‌شوند.\n"
        "هیچ سفارش واقعی ارسال نمی‌شود."
    )


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()

    if not state["open_trades"]:
        await update.message.reply_text(
            "در حال حاضر معامله آزمایشی بازی وجود ندارد."
        )
        return

    result = "📈 معاملات باز آزمایشی\n\n"

    for trade in state["open_trades"]:
        result += (
            f"{trade['symbol']}\n"
            f"ورود: {trade['entry']:.8g}\n"
            f"حد ضرر: {trade['stop']:.8g}\n"
            f"هدف اول: {trade['target1']:.8g}\n"
            f"هدف دوم: {trade['target2']:.8g}\n"
            f"هدف سوم: {trade['target3']:.8g}\n"
            f"حجم باقی‌مانده: "
            f"{trade['remaining_qty']:.8g}\n\n"
        )

    await update.message.reply_text(result)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()

    win_rate = (
        state["wins"] / state["closed_trades"] * 100
        if state["closed_trades"] > 0
        else 0
    )

    await update.message.reply_text(
        "📊 گزارش عملکرد آزمایشی\n\n"
        f"معاملات بسته‌شده: {state['closed_trades']}\n"
        f"معاملات سودده: {state['wins']}\n"
        f"معاملات زیان‌ده: {state['losses']}\n"
        f"درصد برد: {win_rate:.1f}%\n"
        f"سود و زیان تحقق‌یافته: "
        f"{state['total_realized_pnl']:+.2f} USDT\n"
        f"بیشترین افت سرمایه ثبت‌شده: "
        f"{state['max_drawdown'] * 100:.2f}%\n"
        f"معاملات باز: {len(state['open_trades'])}"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - شروع\n"
        "/status - وضعیت\n"
        "/balance - موجودی\n"
        "/risk - تنظیمات ریسک\n"
        "/scan - بررسی قیمت\n"
        "/paper_on - شروع معاملات آزمایشی\n"
        "/paper_off - توقف ورود جدید\n"
        "/trades - معاملات باز\n"
        "/report - گزارش عملکرد"
    )


# =====================================
# STARTUP
# =====================================

async def post_init(app):
    app.create_task(paper_engine(app))


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("paper_on", paper_on))
    app.add_handler(CommandHandler("paper_off", paper_off))
    app.add_handler(CommandHandler("trades", trades))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("help", help_command))

    print("Majed Crypto Trader started")

    app.run_polling()


if __name__ == "__main__":
    main()
