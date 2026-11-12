
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# =========================
# Aggressive Paper Trading
# =========================

START_BALANCE = 100.0
RISK_PER_TRADE = 0.02       # 2% risk per trade
MAX_DAILY_LOSS = 0.06       # 6% maximum daily loss
MAX_POSITION_SIZE = 40.0    # Maximum position value in USDT
MAX_OPEN_TRADES = 3
MARKET = "Spot"
EXCHANGE = "Ourbit"

# فعلاً فقط تنظیمات آزمایشی هستند
MODE = "Paper Trading"
REAL_ORDERS_ENABLED = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 🤖\n"
        "Majed Crypto Trader فعال شد.\n\n"
        "حالت: Aggressive Mode 🔥\n"
        "بازار: Spot\n"
        "معاملات: آزمایشی\n\n"
        "دستورات:\n"
        "/status - وضعیت ربات\n"
        "/balance - موجودی آزمایشی\n"
        "/risk - تنظیمات ریسک\n"
        "/report - گزارش عملکرد\n"
        "/help - راهنما\n\n"
        "هیچ سفارش واقعی ارسال نمی‌شود."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "وضعیت ربات: فعال ✅\n"
        "صرافی هدف: Ourbit\n"
        "بازار: Spot\n"
        "استراتژی: تهاجمی\n"
        "حالت: Paper Trading\n"
        "اتصال قیمت بازار: هنوز پیاده‌سازی نشده\n"
        "ارسال سفارش واقعی: غیرفعال 🔒"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"موجودی اولیه آزمایشی: {START_BALANCE:.2f} USDT\n"
        "این موجودی شبیه‌سازی‌شده است و موجودی حساب صرافی نیست."
    )


async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "تنظیمات حالت تهاجمی 🔥\n\n"
        f"ریسک هر معامله: {RISK_PER_TRADE * 100:.1f}%\n"
        f"حداکثر ضرر روزانه: {MAX_DAILY_LOSS * 100:.1f}%\n"
        f"حداکثر حجم هر معامله: {MAX_POSITION_SIZE:.0f} USDT\n"
        f"حداکثر معاملات هم‌زمان: {MAX_OPEN_TRADES}\n"
        "اهرم: صفر\n"
        "حد ضرر: الزامی\n"
        "حد سود: سه مرحله‌ای\n\n"
        "توجه: این موارد تنظیمات هدف هستند؛ "
        "هنوز موتور اجرای معاملات پیاده‌سازی نشده است."
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "گزارش عملکرد آزمایشی 📊\n\n"
        "تعداد معاملات: 0\n"
        "معاملات سودده: 0\n"
        "معاملات زیان‌ده: 0\n"
        "سود و زیان خالص: 0.00 USDT\n"
        "بیشترین افت سرمایه: هنوز محاسبه نشده\n\n"
        "هنوز معامله آزمایشی ثبت نشده است."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنمای Majed Crypto Trader\n\n"
        "/start - شروع ربات\n"
        "/status - وضعیت ربات\n"
        "/balance - موجودی آزمایشی\n"
        "/risk - تنظیمات ریسک\n"
        "/report - گزارش عملکرد\n\n"
        "ربات فعلاً سفارش واقعی نمی‌فرستد."
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("help", help_command))

    print("Majed Crypto Trader - Aggressive Mode is running")

    app.run_polling()


if __name__ == "__main__":
    main()
