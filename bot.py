
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

START_BALANCE = 100.0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 🤖\n"
        "ربات معاملاتی سمیر فعال شد.\n\n"
        "دستورات:\n"
        "/status - وضعیت ربات\n"
        "/balance - موجودی آزمایشی\n"
        "/help - راهنما\n\n"
        "حالت فعلی: آزمایشی (Paper Trading)"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "وضعیت ربات: فعال ✅\n"
        "صرافی هدف: Ourbit\n"
        "بازار: Spot\n"
        "حالت معاملات: آزمایشی"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"موجودی آزمایشی: {START_BALANCE} USDT"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ربات در مرحله آزمایش است.\n"
        "فعلاً هیچ معامله واقعی انجام نمی‌دهد."
    )

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("help", help_command))

    print("Samir Trading Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
