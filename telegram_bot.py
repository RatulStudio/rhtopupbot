import re
import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8719104198:AAFO4QAH1BenXmn-oUgy1C2k9qB8lFRY59Y')
ADMIN_CHAT_ID = int(os.environ.get('ADMIN_CHAT_ID', '5938131609'))

google_creds = os.environ.get('GOOGLE_CREDENTIALS')
if google_creds:
    cred_dict = json.loads(google_creds)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(cred)
db = firestore.client()
logging.basicConfig(level=logging.INFO)

def parse_sms(text):
    text = text.strip()
    result = {"trxId": None, "amount": None, "method": "bkash", "raw": text}
    trx_patterns = [r'TrxID\s+([A-Z0-9]{6,12})', r'TrxID[:\s]+([A-Z0-9]{6,12})', r'Ref\s+([A-Z0-9]{6,12})']
    amt_patterns = [r'Tk\s*([\d,]+\.?\d*)', r'BDT\s*([\d,]+\.?\d*)']
    t = text.lower()
    if 'nagad' in t: result['method'] = 'nagad'
    elif 'rocket' in t or 'dbbl' in t: result['method'] = 'rocket'
    for p in trx_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m: result['trxId'] = m.group(1).upper(); break
    for p in amt_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try: result['amount'] = float(m.group(1).replace(',',''))
            except: pass
            break
    return result

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🤖 RH TopUp Bot চালু!\nChat ID: `{chat_id}`\n✅ Ready!", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Unauthorized!"); return
    data = parse_sms(text)
    if not data['trxId']:
        await update.message.reply_text("⚠️ TRX ID পাওয়া যায়নি!\nManual: /add TRXID AMOUNT bkash"); return
    if not data['amount']:
        await update.message.reply_text(f"⚠️ Amount পাওয়া যায়নি!\n/add {data['trxId']} 150 bkash"); return
    try:
        existing = db.collection('transactions').where('trxId','==',data['trxId']).get()
        if existing: await update.message.reply_text(f"⚠️ TRX {data['trxId']} already exists!"); return
        db.collection('transactions').add({'trxId':data['trxId'],'amount':int(data['amount']),'method':data['method'],'used':False,'createdAt':datetime.now(),'rawSms':text[:500]})
        await update.message.reply_text(f"✅ TRX Saved!\n📌 `{data['trxId']}`\n💰 ৳{int(data['amount'])}\n📱 {data['method'].upper()}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def add_trx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    args = context.args
    if len(args) < 2: await update.message.reply_text("Usage: /add TRXID AMOUNT METHOD"); return
    trx_id = args[0].upper()
    try: amount = int(args[1])
    except: await update.message.reply_text("❌ Amount সঠিক নয়!"); return
    method = args[2].lower() if len(args) > 2 else 'bkash'
    try:
        existing = db.collection('transactions').where('trxId','==',trx_id).get()
        if existing: await update.message.reply_text(f"⚠️ TRX {trx_id} already exists!"); return
        db.collection('transactions').add({'trxId':trx_id,'amount':amount,'method':method,'used':False,'createdAt':datetime.now(),'rawSms':'Manual'})
        await update.message.reply_text(f"✅ Added!\n📌 `{trx_id}`\n💰 ৳{amount}\n📱 {method.upper()}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_trx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    try:
        docs = db.collection('transactions').limit(10).get()
        if not docs: await update.message.reply_text("কোনো TRX নেই।"); return
        msg = "📋 Transactions:\n\n"
        for doc in docs:
            d = doc.to_dict()
            msg += f"• `{d['trxId']}` — ৳{d['amount']} — {'✅Used' if d.get('used') else '🟢Available'}\n"
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    print("🤖 Starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_trx))
    app.add_handler(CommandHandler("list", list_trx))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Running!")
    app.run_polling()
