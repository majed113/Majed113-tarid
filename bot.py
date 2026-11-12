
import os
import asyncio
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# ===== تنظیمات ربات =====

START_BALANCE = 100.0
RISK_PER_TRADE = 0.02
MAX_DAILY_LOSS = 0.06
MAX_POSITION_SIZE = 40.0
MAX_OPEN_TRADES = 3

API_URL = "https://api.ourbit.com"
REAL_ORDERS_ENABLED = False


# ===== دریافت اطلاعات عمومی بازار =====


def get_market_data():
    base = "https://api.ourbit.com/api/v3"

    # دریافت مشخصات بازارهای مجاز
    info_response = requests.get(
        f"{base}/exchangeInfo", timeout=15
    )
    info_response.raise_for_status()
    info = info_response.json()

    allowed = set()

    for item in info.get("symbols", []):
        symbol = item.get("symbol", "")
        base_asset = item.get("baseAsset", "")

        if (
            item.get("status") == "ENABLED"
            and item.get("isSpotTradingAllowed") is True
            and item.get("quoteAsset") == "USDT"
            and symbol.endswith("USDT")
            and "~" not in symbol
            and base_asset
            and not base_asset.endswith(("YES", "NO"))
        ):
            allowed.add(symbol)

    # دریافت آمار بازار
    response = requests.get(
        f"{base}/ticker/24hr", timeout=15
    )
    response.raise_for_status()

    data = response.json()
    if isinstance(data, dict):
        data = [data]

    markets = []

    for item in data:
        symbol = item.get("symbol", "")

        if symbol not in allowed:
            continue

        try:
            price = float(item["lastPrice"])
            raw_change = float(item["priceChangePercent"])
            volume = float(item.get("quoteVolume") or 0)

            # تبدیل درصد اعشاری به درصد واقعی
            change = (
                raw_change * 100
                if abs(raw_change) <= 1
                else raw_change
            )

            if price <= 0 or volume < 10000:
                continue

            markets.append({
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": volume
            })

        except (ValueError, TypeError, KeyError):
            continue

    return markets


# ===== شروع ربات =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 🤖\n"
        "Majed Crypto Trader فعال شد.\n\n"
        "حالت: Aggressive Mode 🔥\n"
        "بازار: Spot\n"
        "صرافی: Ourbit\n"
        "معاملات: Paper Trading\n\n"
        "/status - وضعیت ربات\n"
        "/balance - موجودی آزمایشی\n"
        "/risk - تنظیمات ریسک\n"
        "/scan - اسکن بازار\n"
        "/report - گزارش عملکرد\n"
        "/help - راهنما\n\n"
        "سفارش واقعی غیرفعال است."
    )


# ===== وضعیت =====

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "وضعیت ربات: فعال ✅\n"
        "صرافی: Ourbit\n"
        "بازار: Spot\n"
        "استراتژی: تهاجمی\n"
        "حالت: Paper Trading\n"
        "دریافت قیمت بازار: فعال\n"
        "موتور معاملات آزمایشی: هنوز فعال نشده\n"
        "سفارش واقعی: غیرفعال 🔒"
    )


# ===== موجودی =====

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"موجودی اولیه آزمایشی: {START_BALANCE:.2f} USDT\n"
        "این مبلغ واقعی نیست."
    )


# ===== تنظیمات ریسک =====

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
        "حالت: آزمایشی"
    )


# ===== اسکن بازار =====

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text(
        "🔎 در حال بررسی بازار Ourbit..."
    )

    try:
        markets = await asyncio.to_thread(get_market_data)

        if not markets:
            await message.edit_text(
                "اطلاعات بازار دریافت شد، اما جفت‌ارز مناسبی پیدا نشد."
            )
            return

        # مرتب‌سازی بر اساس بیشترین نوسان مثبت و منفی
        markets.sort(
            key=lambda x: abs(x["change"]),
            reverse=True
        )

        top_markets = markets[:5]

        result = "📊 گزارش اسکن بازار Ourbit\n\n"

        for index, coin in enumerate(top_markets, start=1):
            direction = (
                "🟢 صعودی"
                if coin["change"] > 0
                else "🔴 نزولی"
            )

            result += (
                f"{index}. {coin['symbol']}\n"
                f"قیمت: {coin['price']:.8g} USDT\n"
                f"تغییر ۲۴ ساعته: "
                f"{coin['change']:+.2f}%\n"
                f"جهت: {direction}\n\n"
            )

        result += (
            "⚠️ این فهرست فقط بر اساس نوسان ۲۴ ساعته است.\n"
            "هنوز سیگنال خرید یا فروش صادر نمی‌شود.\n"
            "هیچ سفارش واقعی ارسال نشده است."
        )

        await message.edit_text(result)

    except requests.RequestException:
        await message.edit_text(
            "❌ اتصال به اطلاعات عمومی Ourbit برقرار نشد.\n"
            "لطفاً کمی بعد دوباره امتحان کن."
        )

    except Exception as error:
        print("Scan error:", error)
        await message.edit_text(
            "خطا در اسکن بازار. جزئیات در لاگ Railway ثبت شد."
        )


# ===== گزارش =====

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 گزارش عملکرد آزمایشی\n\n"
        "تعداد معاملات: 0\n"
        "معاملات سودده: 0\n"
        "معاملات زیان‌ده: 0\n"
        "سود و زیان: 0 USDT\n"
        "افت سرمایه: هنوز محاسبه نشده\n\n"
        "موتور معاملات هنوز پیاده‌سازی نشده است."
    )


# ===== راهنما =====

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنمای ربات:\n\n"
        "/start - شروع\n"
        "/status - وضعیت\n"
        "/balance - موجودی\n"
        "/risk - تنظیمات ریسک\n"
        "/scan - اسکن بازار\n"
        "/report - گزارش\n\n"
        "ربات فعلاً فقط اطلاعات عمومی بازار را دریافت می‌کند."
    )


# ===== اجرای برنامه =====

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("help", help_command))

    print("Majed Crypto Trader is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
