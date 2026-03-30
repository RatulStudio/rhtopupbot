"""
RH TopUp — Telegram Bot
========================
এই Bot টা bKash/Nagad/Rocket SMS forward করলে
TRX ID + Amount Firebase Firestore এ save করবে।

Setup:
1. pip install python-telegram-bot firebase-admin
2. serviceAccountKey.json Firebase থেকে download করুন
3. BOT_TOKEN এবং ADMIN_CHAT_ID পরিবর্তন করুন
4. python telegram_bot.py চালান
"""

import re
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# =============================================
# CONFIGURATION — এখানে আপনার তথ্য দিন
# =============================================
BOT_TOKEN = "8719104198:AAFO4QAH1BenXmn-oUgy1C2k9qB8lFRY59Y"
ADMIN_CHAT_ID = 5938131609  # আপনার Telegram Chat ID

# =============================================
# FIREBASE SETUP
# =============================================
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

logging.basicConfig(level=logging.INFO)

# =============================================
# SMS PARSER — bKash/Nagad/Rocket SMS থেকে TRX বের করে
# =============================================
def parse_sms(text):
    """
    SMS থেকে TRX ID, Amount, Method বের করে।
    """
    text = text.strip()
    result = {"trxId": None, "amount": None, "method": None, "raw": text}

    # ---- bKash ----
    # "You have received Tk 150.00 from 01XXXXXXXXX. TrxID ABCD1234XY"
    # "Tk 150.00 sent to 01XXXXXXXXX from your bKash account. TrxID ABCD1234XY"
    bkash_patterns = [
        r'TrxID\s+([A-Z0-9]{8,12})',
        r'transaction\s+ID[:\s]+([A-Z0-9]{8,12})',
        r'Ref\s+([A-Z0-9]{8,12})',
    ]
    amount_patterns = [
        r'Tk\s*([\d,]+\.?\d*)',
        r'BDT\s*([\d,]+\.?\d*)',
        r'৳\s*([\d,]+\.?\d*)',
    ]

    # Method detect
    text_lower = text.lower()
    if 'bkash' in text_lower or 'b-kash' in text_lower:
        result['method'] = 'bkash'
    elif 'nagad' in text_lower:
        result['method'] = 'nagad'
    elif 'rocket' in text_lower or 'dbbl' in text_lower:
        result['method'] = 'rocket'
    else:
        result['method'] = 'unknown'

    # TRX ID extract
    for pattern in bkash_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result['trxId'] = match.group(1).upper()
            break

    # Amount extract
    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                result['amount'] = float(amount_str)
            except:
                pass
            break

    return result

# =============================================
# /start COMMAND
# =============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🤖 RH TopUp Payment Bot চালু আছে!\n\n"
        f"আপনার Chat ID: `{chat_id}`\n\n"
        f"bKash/Nagad/Rocket SMS forward করলে\n"
        f"আমি automatically TRX save করব।\n\n"
        f"✅ Bot ready!",
        parse_mode='Markdown'
    )

# =============================================
# SMS RECEIVE & PROCESS
# =============================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    # শুধু Admin এর message নেব
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return

    # SMS parse করো
    data = parse_sms(text)

    if not data['trxId']:
        await update.message.reply_text(
            "⚠️ TRX ID পাওয়া যায়নি!\n\n"
            "SMS টা এভাবে forward করুন:\n"
            "bKash SMS → এই bot এ forward করুন"
        )
        return

    if not data['amount']:
        await update.message.reply_text(
            f"⚠️ Amount পাওয়া যায়নি!\n"
            f"TRX: {data['trxId']}\n\n"
            f"Amount manually দিন:\n"
            f"/add {data['trxId']} 150 bkash"
        )
        return

    # Firebase এ save করো
    try:
        # Check duplicate
        existing = db.collection('transactions').where('trxId', '==', data['trxId']).get()
        if existing:
            await update.message.reply_text(f"⚠️ TRX {data['trxId']} already exists!")
            return

        # Save to Firestore
        db.collection('transactions').add({
            'trxId': data['trxId'],
            'amount': int(data['amount']),
            'method': data['method'],
            'used': False,
            'createdAt': datetime.now(),
            'rawSms': text[:500]
        })

        await update.message.reply_text(
            f"✅ TRX Saved Successfully!\n\n"
            f"📌 TRX ID: `{data['trxId']}`\n"
            f"💰 Amount: ৳{int(data['amount'])}\n"
            f"📱 Method: {data['method'].upper()}\n\n"
            f"User এখন এই TRX দিয়ে balance add করতে পারবে!",
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# =============================================
# /add COMMAND — Manual TRX add
# Usage: /add ABC1234XYZ 150 bkash
# =============================================
async def add_trx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_CHAT_ID:
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /add <TRX_ID> <AMOUNT> <METHOD>\n"
            "Example: /add ABC1234XYZ 150 bkash"
        )
        return

    trx_id = args[0].upper()
    try:
        amount = int(args[1])
    except:
        await update.message.reply_text("❌ Amount সঠিক নয়!")
        return

    method = args[2].lower() if len(args) > 2 else 'bkash'

    try:
        # Check duplicate
        existing = db.collection('transactions').where('trxId', '==', trx_id).get()
        if existing:
            await update.message.reply_text(f"⚠️ TRX {trx_id} already exists!")
            return

        db.collection('transactions').add({
            'trxId': trx_id,
            'amount': amount,
            'method': method,
            'used': False,
            'createdAt': datetime.now(),
            'rawSms': f'Manual add by admin'
        })

        await update.message.reply_text(
            f"✅ Manual TRX Added!\n\n"
            f"📌 TRX ID: `{trx_id}`\n"
            f"💰 Amount: ৳{amount}\n"
            f"📱 Method: {method.upper()}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# =============================================
# /list COMMAND — Last 10 TRX দেখুন
# =============================================
async def list_trx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_CHAT_ID:
        return

    try:
        docs = db.collection('transactions').order_by(
            'createdAt', direction=firestore.Query.DESCENDING
        ).limit(10).get()

        if not docs:
            await update.message.reply_text("কোনো TRX নেই।")
            return

        msg = "📋 Last 10 Transactions:\n\n"
        for doc in docs:
            d = doc.to_dict()
            status = "✅ Used" if d.get('used') else "🟢 Available"
            msg += f"• `{d['trxId']}` — ৳{d['amount']} — {status}\n"

        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# =============================================
# MAIN
# =============================================
if __name__ == '__main__':
    print("🤖 RH TopUp Bot starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_trx))
    app.add_handler(CommandHandler("list", list_trx))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Forward bKash SMS to the bot.")
    app.run_polling()
