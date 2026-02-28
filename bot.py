import time
import time
import asyncio
import os
import re
import logging
import sqlite3

from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from urllib.parse import urlparse, parse_qs

# -----------------------
# ตั้งค่า/ข้อความที่ปรับเองได้
# -----------------------
TOKEN = os.environ.get("BOT_TOKEN")  # ใส่ใน env เหมือนเดิม
ADMIN_ID = 6682802546

PENDING_LINKS: dict[str, float] = {}
PENDING_TTL_SEC = 2 * 24 * 60 * 60

SHORT_CD = 10
LONG_CD = 10 * 6


DB_PATH = "used_v.sqlite3"

def init_used_v_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS used_v (
            v TEXT PRIMARY KEY,
            first_seen_at INTEGER
        )
    """)
    conn.commit()
    conn.close()

def extract_truemoney_v(url: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        return qs.get("v", [None])[0]
    except Exception:
        return None

def is_v_used(v: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM used_v WHERE v = ? LIMIT 1", (v,))
    row = cur.fetchone()
    conn.close()
    return row is not None

def mark_v_used(v: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO used_v (v, first_seen_at) VALUES (?, strftime('%s','now'))",
        (v,)
    )
    conn.commit()
    conn.close()

def is_link_pending(url: str) -> bool:
    now = time.time()

    # ลบตัวที่หมดอายุ
    expired = [u for u, exp in PENDING_LINKS.items() if exp <= now]
    for u in expired:
        PENDING_LINKS.pop(u, None)

    return url in PENDING_LINKS


def mark_link_pending(url: str):
    PENDING_LINKS[url] = time.time() + PENDING_TTL_SEC


def unmark_link_pending(url: str):
    PENDING_LINKS.pop(url, None)

PAY_IMAGE_PATH = "bottele.jpg"        # รูปตัวอย่างชำระเงิน (อยู่โฟลเดอร์เดียวกับ bot.py)
PRICE_TEXT = "ราคา: 650 บาท"         # แก้เป็นราคาจริง
CONTACT_TEXT = "ช่องทางติดต่อแอดมิน: @Dok_tong"

PAY_HELP_TEXT = (
    "วิธีชำระเงิน: ซองทรูมันนี่เท่านั้น\n"
    f"{PRICE_TEXT}\n\n"
    "บันทึก 'รูปซอง QR' เข้ามาในแชทนี้ได้เลย\n"
    "หากส่งเป็นลิ้งลิ้งก์ บอทจะตรวจสอบ 5 นาที\n\n"
    "⚠️ ตรวจสอบอายุลิงก์ก่อนส่ง (แนะนำ 1-3 วัน)\n"
    "ลิงก์หมดอายุ ต้องสร้างใหม่ค่ะ"
)

SUCCESS_TEXT = "รับข้อมูลเรียบร้อยค่ะ ✅\nแอดมินกำลังตรวจสอบให้นะคะ 🙂"
FAIL_TEXT = "ตรวจสอบไม่พบค่ะ ❌\nกรุณาส่งใหม่อีกครั้ง (ลิงก์ซองทรูมันนี่ หรือรูป QR เท่านั้นนะคะ)"

# โดเมนที่ “อนุญาต” ให้ผ่านการตรวจแบบพื้นฐาน (ปรับได้)
ALLOWED_DOMAINS = {
    "tmn.app",
    "gift.truemoney.com",
}

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# ฟังก์ชันช่วยเช็ค “แชทส่วนตัวเท่านั้น”
# -----------------------
def is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE

async def private_only_notice(update: Update):
    if update.message:
        await update.message.reply_text("บอทนี้ใช้ในแชทส่วนตัวเท่านั้นนะคะ 🙂")

def sender_label(update: Update) -> tuple[str, str]:
    u = update.effective_user
    if not u:
        return ("unknown", "unknown")
    name = u.first_name or "unknown"
    if u.username:
        name = f"{name} (@{u.username})"
    return (name, str(u.id))

# -----------------------
# ดึง URL
# -----------------------
URL_REGEX = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

def extract_first_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_REGEX.search(text)
    return m.group(1) if m else None

def extract_first_url_from_message(msg) -> str | None:
    """
    ดึง url ตัวแรกจาก message (รองรับทั้ง url ธรรมดา และ text_link)
    """
    if not msg:
        return None

    # entity ก่อน (แม่นกว่า)
    if msg.entities:
        text = msg.text or ""
        for e in msg.entities:
            if e.type == "url":
                return text[e.offset:e.offset + e.length]
            if e.type == "text_link":
                return e.url

    # fallback regex
    text = msg.text or ""
    return extract_first_url(text)

# -----------------------
# ตรวจลิงก์แบบพื้นฐาน (กรองเบื้องต้น)
# -----------------------
def basic_verify_truemoney_link(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False

        host = (p.netloc or "").lower().split(":")[0]
        return host in ALLOWED_DOMAINS
    except Exception:
        return False

# -----------------------
# QR Decode (จากรูป) - OPTIONAL
# ถ้าเครื่องยังไม่มี lib จะอ่านไม่ได้ แต่โค้ดจะไม่พัง
# -----------------------
def try_decode_qr_from_image_bytes(img_bytes: bytes) -> list[str]:
    results: list[str] = []
    try:
        from PIL import Image
        from io import BytesIO
        from pyzbar.pyzbar import decode

        im = Image.open(BytesIO(img_bytes))
        decoded = decode(im)
        for obj in decoded:
            try:
                results.append(obj.data.decode("utf-8", errors="ignore"))
            except Exception:
                pass
    except Exception as e:
        logger.info(f"QR decode not available/failed: {e}")
    return results

# -----------------------
# คำสั่ง /start
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    text = (
        "สวัสดีค่ะ 👋\n\n"
        f"{CONTACT_TEXT}\n\n"
        "เมนู:\n"
        "• /payment = วิธีชำระเงิน\n"
    )
    await update.message.reply_text(text)

# -----------------------
# คำสั่ง /payment
# -----------------------
async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return await private_only_notice(update)

    await update.message.reply_text(PAY_HELP_TEXT)

    # ส่งรูปตัวอย่าง (ถ้ามีไฟล์)
    try:
        if os.path.exists(PAY_IMAGE_PATH):
            with open(PAY_IMAGE_PATH, "rb") as f:
                await update.message.reply_photo(photo=f)
        else:
            await update.message.reply_text("⚠️ ยังไม่พบไฟล์รูปตัวอย่าง")
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("ส่งรูปตัวอย่างไม่สำเร็จ")

# -----------------------
# รับข้อความ (ลิงก์)
# -----------------------
async def delete_after(msg, sec: int):
    try:
        await asyncio.sleep(sec)
        await msg.delete()
    except Exception:
        pass

async def delayed_thanks_for_link(chat_id: int, context, url: str, reply_to_msg_id: int,
                                  wait_sec: int = 130, delete_after_sec: int = 300):
    await asyncio.sleep(wait_sec)

    try:
        final_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"thanks! ✅ https://t.me/+EeRmJja2LB85OWM1",
            reply_to_message_id=reply_to_msg_id
        )
    except Exception as e:
        print("Reply failed, sending normal:", e)
        final_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"thanks! ✅ https://t.me/+EeRmJja2LB85OWM1"
        )

    context.application.create_task(delete_after(final_msg, delete_after_sec))

async def delete_after(msg, sec: int):
    await asyncio.sleep(sec)
    try:
        await msg.delete()
    except Exception:
        pass

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message  
    if not msg:
        return

    if msg.chat.type != ChatType.PRIVATE:
        return

    text = (msg.text or "").strip()
    if not text:
        return

    now = time.time()

    url = extract_first_url_from_message(msg)
    if not url:
        # ---------- กันทักซ้ำ (กรณีส่งข้อความที่ไม่ใช่ลิงก์) ----------
        # ลำดับตอบ:
        # 1) ตอบ "ข้อความที่ 1" (ครั้งที่ 1)
        # 2) รออย่างน้อย 5 วิ -> ตอบ "ข้อความที่ 1" (ครั้งที่ 2)
        # 3) หลังครั้งที่ 2 -> เงียบ 10 วิ
        # 4) หลังพ้น 10 วิ (และยังทักซ้ำ) -> ตอบ "ข้อความที่ 2: ไม่ทักซ้ำนะ"
        # 5) หลังตอบข้อความที่ 2 -> เงียบยาว 10 นาที แล้วค่อยวนใหม่ได้

        msg1 = "📩 หากต้องการติดต่อสอบถามเพิ่มเติม กรุณาทักมาที่ @Dok_tong ได้เลยนะคะ"
        msg2 = "รบกวนไม่ทักซ้ำนะคะ🙂"

        # lock กันข้อความเข้ามาถี่ๆ (async ซ้อนกัน) ทำให้ตอบรัว
        user_id = msg.from_user.id if msg.from_user else None
        locks = context.application.bot_data.setdefault("user_locks", {})
        lock = locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[user_id] = lock

        async with lock:
            stage = int(context.user_data.get("nonurl_stage", 0))
            last_sent = float(context.user_data.get("nonurl_last_sent", 0.0))
            silence_until = float(context.user_data.get("nonurl_silence_until", 0.0))

            # stage 3 = เงียบยาว 10 นาที
            if stage == 3:
                if now < silence_until:
                    return
                # ครบเวลาแล้ว -> รีเซ็ต แล้วให้เข้า stage 0 ต่อได้
                stage = 0
                last_sent = 0.0
                silence_until = 0.0
                context.user_data["nonurl_stage"] = 0
                context.user_data["nonurl_last_sent"] = 0.0
                context.user_data["nonurl_silence_until"] = 0.0

            # stage 0: ตอบ msg1 ครั้งที่ 1
            if stage == 0:
                await msg.reply_text(msg1)
                context.user_data["nonurl_stage"] = 1
                context.user_data["nonurl_last_sent"] = now
                return

            # stage 1: ตอบ msg1 ครั้งที่ 2 (ต้องห่างจากครั้งแรก >= 5 วิ)
            if stage == 1:
                if now - last_sent < 5:
                    return
                await msg.reply_text(msg1)
                context.user_data["nonurl_stage"] = 2
                context.user_data["nonurl_last_sent"] = now
                return

            # stage 2: หลังตอบครั้งที่ 2 -> เงียบ 10 วิ แล้วค่อยตอบ msg2
            if stage == 2:
                if now - last_sent < 10:
                    return
                await msg.reply_text(msg2)
                context.user_data["nonurl_stage"] = 3
                context.user_data["nonurl_last_sent"] = now
                context.user_data["nonurl_silence_until"] = now + 600  # 10 นาที
                return

        return


    # ตัดเศษท้ายลิงก์ (กันเคสมี ) ] > , . ต่อท้าย)
    url = url.strip().rstrip(').,;:\'"}]> \n\t')

    # รับเฉพาะ “ซองทรูมันนี่” ตามโดเมนที่กำหนด
    if not basic_verify_truemoney_link(url):
        await msg.reply_text(FAIL_TEXT)
        return

    # แจ้งแอดมินว่าใครส่งมา
    sender, sender_id = sender_label(update)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "📩 มีคนส่งลิงก์ซองทรูมันนี่\n"
            f"ผู้ส่ง: {sender}\n"
            f"User ID: {sender_id}\n"
            f"ลิงก์: {url}"
        )
    )
    if is_link_pending(url):
        await msg.reply_text("เอ๊ะ! ลิ้งเดิม...ใจเย็นๆไม่ต้องส่งซ้ำเดี๋ยวระบบงอน 😆")
        return

    mark_link_pending(url)

    # ตอบลูกค้า 2 รอบ (ฟีลมีระบบ)
    chat_id = update.effective_chat.id
    msg = update.message

    processing_msg = await msg.reply_text(
        "⏳ ระบบกำลังตรวจสอบลิงก์ที่ท่านส่งมา\n"
         "ระยะเวลาดำเนินการประมาณ 2-5 นาที\n\n"
         "📌 เพื่อความรวดเร็ว สามารถบันทึกรูป QR Code ส่งมาเพิ่มเติมได้ค่ะ"
    )   
    context.application.create_task(
        delayed_thanks_for_link(
            chat_id=chat_id,
            context=context,
            url=url,
            reply_to_msg_id=processing_msg.message_id,
            wait_sec=130,
            delete_after_sec=300
        )
    )

# -----------------------
# รับรูป (QR/หลักฐาน) - รับหมดเพื่อกันลูกค้าส่งรูปอย่างเดียว
# -----------------------
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return

    msg = update.message
    if not msg or not msg.photo:
        return

    sender, sender_id = sender_label(update)

    # โหลดรูป (เอาความละเอียดสูงสุด)
    decoded = []
    try:
        file = await msg.photo[-1].get_file()
        img_bytes = await file.download_as_bytearray()
        decoded = try_decode_qr_from_image_bytes(bytes(img_bytes))
    except Exception as e:
        logger.info(f"QR decode step failed: {e}")
        decoded = []

    # แจ้งแอดมินทุกครั้ง + บอกผลสแกน
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🧾 มีคนส่งรูปหลักฐาน/QR\n"
            f"ผู้ส่ง: {sender}\n"
            f"User ID: {sender_id}\n"
            f"ผลสแกน: {'✅ พบ QR' if decoded else '❌ ไม่พบ/อ่านไม่ได้'}"
        )
    )
    # forward รูปให้แอดมินทุกครั้ง
    await context.bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=msg.chat_id,
        message_id=msg.message_id
    )

    processing_msg = await msg.reply_text("⏳ กำลังตรวจสอบ รอสักครู่นะคะ…")
    await asyncio.sleep(5)

    if decoded:
        # ส่งค่าที่อ่านได้ให้แอดมิน            
        tm_links = [d for d in decoded if "gift.truemoney.com" in d]
        if tm_links:
            latest = tm_links[-1]
        else:
            latest = decoded[-1]

        v = extract_truemoney_v(latest)
        if not v:
            await processing_msg.edit_text("❌ ตรวจสอบเสร็จแล้ว: ไม่พบข้อมูลในลิงก์ค่ะ")
            last_msg = await msg.reply_text("❌ รูปนี้อ่านเจอลิงก์ แต่ไม่พบรหัส v ค่ะ ส่งใหม่อีกครั้งนะคะ")
            asyncio.create_task(delete_after(last_msg, 120))
            return

        if is_v_used(v):
            await processing_msg.edit_text("⚠️ ตรวจสอบเสร็จแล้ว: รายการนี้ถูกตรวจไปแล้วค่ะ")
            last_msg = await msg.reply_text("❌ QR/ลิงก์นี้เคยตรวจไปแล้วนะคะ (กันซ้ำถาวร)")
            asyncio.create_task(delete_after(last_msg, 120))
            return

        mark_v_used(v)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="🔎 QR ที่อ่านได้ (ล่าสุด):\n" + latest
        )

        await processing_msg.edit_text("✅ ตรวจสอบเสร็จแล้วค่ะ")

        last_msg = await msg.reply_text(
            "🎉 ทำรายการสำเร็จ\n"
            "⚠️ ลิงก์เข้ากลุ่มจะถูกลบอัตโนมัติภายใน 5 นาที\n"
            "กรุณาเข้ากลุ่มทันทีค่ะ\n\n"
            "https://t.me/+EeRmJja2LB85OWM1"
        )
        asyncio.create_task(delete_after(last_msg, 300))

    else:
        await processing_msg.edit_text("❌ ตรวจสอบเสร็จแล้ว: อ่าน QR ไม่ได้ค่ะ")
        last_msg = await msg.reply_text(
            "❌ อ่าน QR ไม่ได้ค่ะ\n"
            "รบกวนส่งรูปที่ชัดขึ้น/สกรีนช็อต QR อีกครั้งนะคะ"
        )
        asyncio.create_task(delete_after(last_msg, 120))

# -----------------------
# main
# -----------------------
def main():
    if not TOKEN:
        raise RuntimeError("ไม่พบ BOT_TOKEN ใน environment (export BOT_TOKEN ก่อนรัน)")

    init_used_v_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("payment", payment))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    app.run_polling()

if __name__ == "__main__":
    main()