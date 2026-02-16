from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

import os
TOKEN = os.environ.get("BOT_TOKEN")
print("TOKEN VALUE:", TOKEN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ติดต่อสอบถาม @Dok_tong")

async def call_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📢 เรียกแอดมินแล้วครับ!")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:

        text = """
📋 <b><u>กฎกลุ่ม</u></b> <b>ตลาดล่าง V.2</b>
━━━━━━━━━━━━

🔴 <b>ไม่ขายงานทุกกรณี</b>  
ไม่โปรโมทแฝง ไม่ทักขาย ไม่ตั้งไบโอชวนซื้อ  
พบเห็น = <b>แจกตั๋วบินฟรี</b>

━━━━━━━━━━━━

🟠 <b>งดเนื้อหาไม่เหมาะสม</b>  
• งานเป / ชุดนร.  
• อาวุธ เลือด เนื้อหารุนแรง  
• งานเสี่ยงลบ  

━━━━━━━━━━━━

🟡 <b>ไม่โพสต์แบบเดิมซ้ำ ๆ</b>  
ลงแล้วรอได้ ไม่ต้องเร่ง ไม่ต้องย้ำบ่อย  

━━━━━━━━━━━━━

🛡 หากพบเจอมิจจี้ หรือใครทำผิดกฎ
สามารถพิมพ์ว่า> <b><u>@admin</u></b> ได้เลย เดี๋ยวแอดมินเข้าดูให้
"""

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="HTML"
        )

roasts = [
    "เรียกทำไม มีเรื่องเหรอ 😏",
    "บอทอยู่นี่ แล้วสมองเธออยู่ไหน 555",
    "เรียกอีกที เดี๋ยวคิดคำแรงกว่านี้ให้ 😆",
    "มาถูกคนแล้ว แต่ถามให้ถูกก่อนนะ",
    "มีอะไรจะสารภาพไหม 🤨"
]

async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        text = update.message.text.lower()

        # ถ้ามีคำว่า บอท หรือมีการ mention
        if "บอท" in text or update.message.entities:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=random.choice(roasts)
            )   

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(
    MessageHandler(filters.TEXT & filters.Regex(r"@admin"), call_admin)
)
app.add_handler(CommandHandler("rules", rules))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, roast))


app.run_polling()
