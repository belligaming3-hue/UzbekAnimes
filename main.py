import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta, date
import logging
import re  # Kanal o'chirish uchun regex qo'shildi
from io import StringIO  # TXT fayl uchun
import time  # Restart uchun qo'shildi
import sys  # Sys.exit uchun, lekin ishlatilmaydi
import json  # Export uchun

# Logging sozlash
logging.basicConfig(level=logging.INFO)

# Bot tokenini o'zingiznikiga almashtiring
BOT_TOKEN = '8050815676:AAF8RPwoLCqpzaC4-4EjKwCWbkQzpAYutFg'
bot = telebot.TeleBot(BOT_TOKEN)

# Ma'lumotlar bazasini yaratish
DB_NAME = 'anime_bot.db'

# Date adapterlari (Python 3.12 uchun)
def adapt_date_iso(val):
    return val.isoformat()

def convert_date(val):
    return date.fromisoformat(val.decode())

sqlite3.register_adapter(date, adapt_date_iso)
sqlite3.register_converter("date", convert_date)

def init_db():
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    
    # Foydalanuvchilar jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date DATE,
            subscribed BOOLEAN DEFAULT 0
        )
    ''')
    
    # subscribed ustunini qo'shish agar mavjud bo'lmasa
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'subscribed' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN subscribed BOOLEAN DEFAULT 0")
        logging.info("Subscribed ustuni qo'shildi.")
    
    # Adminlar jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            admin_id INTEGER PRIMARY KEY
        )
    ''')
    
    # Kanallar uchun jadval yaratish (yangi struktura: title va invite_link qo'shildi)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id INTEGER PRIMARY KEY,
            link TEXT,
            title TEXT,
            invite_link TEXT
        )
    ''')
    
    # Anime jadvali: kod, nom, fasllar soni, yuklash vaqti, sarlavha, sarlavha_rasmi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS animes (
            code TEXT PRIMARY KEY,
            name TEXT,
            seasons_count INTEGER,
            upload_date DATE,
            header TEXT DEFAULT '',
            header_image_file_id TEXT DEFAULT ''
        )
    ''')
    
    # seasons_count ustunini qo'shish agar mavjud bo'lmasa
    cursor.execute("PRAGMA table_info(animes)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'seasons_count' not in columns:
        cursor.execute("ALTER TABLE animes ADD COLUMN seasons_count INTEGER DEFAULT 1")
        logging.info("Seasons_count ustuni qo'shildi.")
    
    # header ustunini qo'shish
    if 'header' not in columns:
        cursor.execute("ALTER TABLE animes ADD COLUMN header TEXT DEFAULT ''")
        logging.info("Header ustuni qo'shildi.")
    
    # header_image_file_id ustunini qo'shish
    if 'header_image_file_id' not in columns:
        cursor.execute("ALTER TABLE animes ADD COLUMN header_image_file_id TEXT DEFAULT ''")
        logging.info("Header_image_file_id ustuni qo'shildi.")
    
    # Anime fasllari: kod, fasl raqami, qismlar soni
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            season_num INTEGER,
            parts_count INTEGER,
            FOREIGN KEY (code) REFERENCES animes (code)
        )
    ''')
    
    # Anime qismlari: kod, fasl raqami, qism raqami, file_id, caption
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            season_num INTEGER,
            part_num INTEGER,
            file_id TEXT,
            caption TEXT,
            FOREIGN KEY (code) REFERENCES animes (code)
        )
    ''')
    
    # season_num ustunini qo'shish agar mavjud bo'lmasa
    cursor.execute("PRAGMA table_info(anime_parts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'season_num' not in columns:
        cursor.execute("ALTER TABLE anime_parts ADD COLUMN season_num INTEGER")
        logging.info("Season_num ustuni qo'shildi to anime_parts.")
    
    # Oylik va haftalik statistika uchun foydalanuvchi faolligi
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            activity_date DATE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Broadcast mode uchun temp jadval (forward uchun)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broadcast_mode (
            admin_id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'text'  -- 'text' yoki 'forward'
        )
    ''')
    
    # Broadcast content temp: admin_id, content_type ('text'|'photo'|'video'), content (text/file_id), caption
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broadcast_content (
            admin_id INTEGER PRIMARY KEY,
            content_type TEXT,
            content TEXT,
            caption TEXT
        )
    ''')
    
    # Pending joins jadvali (yangi qo'shildi)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id INTEGER,
            request_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Bot sozlamalari: to'xtatish va bildirishnoma
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            id INTEGER PRIMARY KEY,
            bot_stopped BOOLEAN DEFAULT 0,
            notification_enabled BOOLEAN DEFAULT 0,
            notification_channel_id INTEGER DEFAULT NULL
        )
    ''')
    # Dastlabki qiymatni qo'shish
    cursor.execute('INSERT OR IGNORE INTO bot_settings (id) VALUES (1)')
    
    # Dastlabki adminni qo'shish
    default_admin = 5668810530
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id) VALUES (?)', (default_admin,))
    
    # Dastlabki kanal qo'shish (agar kerak bo'lsa, chat_id va link bilan)
    # Misol: default_channel_id = -1001234567890  # Kanal chat_id
    # default_link = '@AniRude1'
    # cursor.execute('INSERT OR IGNORE INTO channels (channel_id, link) VALUES (?, ?)', (default_channel_id, default_link))
    
    conn.commit()
    conn.close()

init_db()

# Default admin ID
DEFAULT_ADMIN_ID = 5668810530

# Bot holatini tekshirish funksiyasi
def is_bot_stopped():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT bot_stopped FROM bot_settings WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else False

# Botni to'xtatish/yoqish
def set_bot_stopped(stopped):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE bot_settings SET bot_stopped = ? WHERE id = 1', (stopped,))
    conn.commit()
    conn.close()

# Bildirishnoma sozlamalari
def get_notification_settings():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT notification_enabled, notification_channel_id FROM bot_settings WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return {'enabled': result[0] if result else False, 'channel_id': result[1] if result and result[1] else None}

def set_notification_enabled(enabled):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE bot_settings SET notification_enabled = ? WHERE id = 1', (enabled,))
    conn.commit()
    conn.close()

def set_notification_channel(channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE bot_settings SET notification_channel_id = ? WHERE id = 1', (channel_id,))
    conn.commit()
    conn.close()

# Kanallar bilan bog'liq funksiyalar
def get_all_channels():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, link, title, invite_link FROM channels')
    channels = cursor.fetchall()
    conn.close()
    return channels

def add_channel(channel_id, link, title, invite_link=''):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO channels (channel_id, link, title, invite_link) VALUES (?, ?, ?, ?)', (channel_id, link, title, invite_link))
    conn.commit()
    conn.close()

def remove_channel(channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

def add_pending_join(user_id, channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO pending_joins (user_id, channel_id, request_date) VALUES (?, ?, ?)",
                   (user_id, channel_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def is_pending_join(user_id, channel_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pending_joins WHERE user_id = ? AND channel_id = ?", (user_id, channel_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def check_all_subscriptions(user_id):
    channels = get_all_channels()
    if not channels:
        return True, []
    missing = []
    for channel_id, link, title, invite_link in channels:
        is_member = False
        try:
            member = bot.get_chat_member(channel_id, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                is_member = True
        except:
            pass
        
        is_private = bool(invite_link)
        if is_private and is_pending_join(user_id, channel_id):
            continue  # Pending so'rov bor, ok deb hisobla
        
        if not is_member:
            missing.append((channel_id, link, title, invite_link))
    return len(missing) == 0, missing

def get_unsubscribed_channels(user_id):
    _, missing = check_all_subscriptions(user_id)
    return missing

def check_subscriptions(user_id):
    all_sub, missing = check_all_subscriptions(user_id)
    if all_sub:
        return True, None
    else:
        ch_id, link, title, invite_link = missing[0]
        title_out = title or link
        return False, title_out

def delete_channel_by_identifier(identifier):
    """Kanalni ID, @username yoki link bilan o'chirish"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Agar ID bo'lsa
    if identifier.isdigit() or (identifier.startswith('-') and identifier[1:].isdigit()):
        channel_id = int(identifier)
        cursor.execute('DELETE FROM channels WHERE channel_id=?', (channel_id,))
    else:
        # @username yoki link bo'lsa, get_chat bilan topish
        try:
            chat = bot.get_chat(identifier)
            channel_id = chat.id
            cursor.execute('DELETE FROM channels WHERE channel_id=?', (channel_id,))
        except:
            # Agar topilmasa, link bo'yicha qidirish
            cursor.execute('DELETE FROM channels WHERE link=? OR invite_link=?', (identifier, identifier))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_channels():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, link, title, invite_link FROM channels')
    channels = cursor.fetchall()
    conn.close()
    return channels

# Foydalanuvchini bazaga qo'shish va faollik qo'shish
def add_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, subscribed) VALUES (?, ?, ?, ?, 0)',
                   (user_id, username, first_name, date.today()))
    cursor.execute('INSERT OR IGNORE INTO user_activity (user_id, activity_date) VALUES (?, ?)',
                   (user_id, date.today()))
    conn.commit()
    conn.close()

# Admin tekshirish
def is_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE admin_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Broadcast mode o'rnatish (forward yoki text)
def set_broadcast_mode(admin_id, mode):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO broadcast_mode (admin_id, mode) VALUES (?, ?)', (admin_id, mode))
    conn.commit()
    conn.close()

def get_broadcast_mode(admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT mode FROM broadcast_mode WHERE admin_id = ?', (admin_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 'text'

# Broadcast content saqlash
def set_broadcast_content(admin_id, content_type, content, caption=''):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO broadcast_content (admin_id, content_type, content, caption) VALUES (?, ?, ?, ?)', 
                   (admin_id, content_type, content, caption))
    conn.commit()
    conn.close()

def get_broadcast_content(admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT content_type, content, caption FROM broadcast_content WHERE admin_id = ?', (admin_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {'type': result[0], 'content': result[1], 'caption': result[2]}
    return None

def clear_broadcast_content(admin_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM broadcast_content WHERE admin_id = ?', (admin_id,))
    conn.commit()
    conn.close()

# Foydalanuvchilarga xabar yuborish (admin uchun, markup bilan) - text/photo/video
def send_broadcast_content(admin_id, markup=None):
    if not is_admin(admin_id):
        return 0
    content = get_broadcast_content(admin_id)
    if not content:
        return 0
    ctype = content['type']
    ccontent = content['content']
    ccapt = content['caption']
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE subscribed = 1')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    success_count = 0
    for user_id in users:
        try:
            if ctype == 'text':
                bot.send_message(user_id, ccontent, reply_markup=markup, parse_mode='HTML')
            elif ctype == 'photo':
                bot.send_photo(user_id, ccontent, caption=ccapt, reply_markup=markup, parse_mode='HTML')
            elif ctype == 'video':
                bot.send_video(user_id, ccontent, caption=ccapt, reply_markup=markup, parse_mode='HTML')
            success_count += 1
        except Exception as e:
            logging.error(f"Xabar yuborish xatosi {user_id}: {e}")
    clear_broadcast_content(admin_id)
    return success_count

# Foydalanuvchilarga forward xabar yuborish (forward mode uchun) - tuzatilgan
def send_broadcast_forward(message, admin_id):
    if not is_admin(admin_id):
        return 0
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE subscribed = 1')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    success_count = 0
    from_chat_id = (message.forward_from_chat.id if message.forward_from_chat 
                    else (message.forward_from.id if message.forward_from else message.chat.id))
    message_id_to_forward = message.forward_message_id or message.message_id
    
    for user_id in users:
        try:
            bot.forward_message(user_id, from_chat_id, message_id_to_forward)
            success_count += 1
        except Exception as e:
            logging.error(f"Forward xatosi {user_id}: {e}")
    return success_count

# Xavfsiz edit_message_text - duplicate yuborishni oldini olish uchun, yangi xabar yuborishda oldingi delete qilish
def safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=None, parse_mode=None):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 400 and ("message is not modified" in e.description or "message can't be edited" in e.description):
            pass  # O'zgarish yo'q, e'tiborsiz qoldirish - duplicate bo'lmaydi
        elif e.error_code == 400 and "message to edit not found" in e.description:
            # Topilmasa, yangi yuborish, lekin oldingi delete qilishga urinmaslik
            bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            raise e

# Xavfsiz delete_message
def safe_delete_message(bot, chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 400 and ("message to delete not found" in e.description or "message can't be deleted" in e.description):
            pass  # Topilmadi, e'tiborsiz qoldir
        else:
            raise e

# Pagination uchun callback data
def get_pagination_callback(code, season_num, page):
    return f"pag_{code}_{season_num}_{page}"

# /namuna komandasi - TXT fayl yuborish (HTML taglari ko'rinadigan qilib)
@bot.message_handler(commands=['namuna'])
def namuna_handler(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "<b>❌ Admin huquqi kerak!</b>", parse_mode='HTML')
        return
    sample = """📢 Xabar matnini kiriting (HTML formatida):

Namuna:
Salom! Bu qalin va kursiv matn.
<b>Qalin matn</b>
<i>Kursiv matn</i>
<u>Underline</u>
<s>Strike</s>
<code>Monospaced matn</code>
<a href="https://example.com">Link</a>
<tg-spoiler>Spoiler</tg-spoiler>

Yoki oddiy matn yozing."""
    # TXT fayl yaratish - HTML taglari matn sifatida ko'rinadi, copy qilganda ishlaydi
    file_io = StringIO(sample)
    bot.send_document(message.chat.id, document=types.InputFile(file_io, 'namuna.txt'), caption="📝 Broadcast namunasi TXT fayl sifatida (HTML taglari ko'rinadi)")

# Global handler for /start and /admin - oldingi jarayonlarni to'xtatish uchun
@bot.message_handler(commands=['start', 'admin'])
def global_command_handler(message):
    cmd = message.text.split()[0]
    if cmd == '/start':
        start_handler(message)
    elif cmd == '/admin':
        admin_command(message)

# Bot to'xtatilgan bo'lsa, foydalanuvchi xabarlariga javob
def handle_bot_stopped(chat_id, user_id, message_id=None):
    if is_admin(user_id):
        return False  # Adminlarga ta'sir qilmaydi
    text = "<b>🔧 Bot vaqtinchalik toʻxtatildi!</b>\n\n<i>Bot yangilanmoqda yoki adminlar anime qo'shmoqda. Iltimos, kuting yoki asosiy adminga murojaat qiling.</i>"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("👨‍💼 Asosiy admin - @rude_lxz", url="https://t.me/rude_lxz"))
    if message_id:
        safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    return True

# /start komandasi (deep link bilan) - Kanallar inline tugmalarda
@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    add_user(user_id, username, first_name)
    
    if is_bot_stopped() and not is_admin(user_id):
        handle_bot_stopped(message.chat.id, user_id)
        return
    
    if len(message.text.split()) > 1:
        # Deep link: kod bilan start
        code = message.text.split()[1]
        subscribed, missing_channel = check_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
            # Anime sarlavhasi va ma'lumotlarini olish
            cursor.execute('SELECT name, seasons_count, header, header_image_file_id FROM animes WHERE code = ?', (code,))
            anime = cursor.fetchone()
            conn.commit()
            if anime:
                name, seasons_count, header, header_image_file_id = anime
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton("📥 Yuklab olish", callback_data=f"download_{code}"))
                if header_image_file_id:
                    bot.send_photo(message.chat.id, header_image_file_id, caption=header or f"<b>🎌 Anime: {code}</b>", reply_markup=markup, parse_mode='HTML')
                elif header:
                    bot.send_message(message.chat.id, header, reply_markup=markup, parse_mode='HTML')
                else:
                    text = f"<b>🎌 Anime: {code}</b>\n<i>Qaysi faslni koʻrmoqchisiz?</i>"
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    for s in range(1, seasons_count + 1):
                        markup.add(types.InlineKeyboardButton(f"📺 Fasl {s}", callback_data=f"season_{code}_{s}"))
                    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')
            conn.close()
            return
        else:
            # Obuna talab qilish
            show_subscription_prompt(message.chat.id, None, missing_channel, user_id)
            return
    else:
        # Oddiy start
        subscribed, missing_channel = check_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            greeting = f"<b>👋 Assalomu aleykum, {first_name}!</b>\n\n<i>Bu botda hamma turdagi animelar mavjud. Iltimos, anime kodini kiriting.</i>\n📢 <b>Kodlar bor kanalga kiring yoki admin bilan bogʻlaning.</b>"
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🔑 Kod kiritish", callback_data="enter_code"),
                types.InlineKeyboardButton("📺 Kodlar Kanali", url="https://t.me/AniRude1"),
                types.InlineKeyboardButton("👨‍💼 Admin bilan bogʻlanish", url="https://t.me/rude_lxz")
            )
            
            bot.send_message(message.chat.id, greeting, reply_markup=markup, parse_mode='HTML')
        else:
            show_subscription_prompt(message.chat.id, None, missing_channel, user_id)

def show_subscription_prompt(chat_id, message_id, missing_channel=None, user_id=None):
    if user_id is None:
        logging.error("User ID topilmadi show_subscription_prompt da")
        return
    unsubscribed = get_unsubscribed_channels(user_id)
    text = f"<b>🔒 Majburiy obuna!</b>\n\n<i>Barcha kanallarga obuna boʻling.</i>\n\nObuna boʻlgandan keyin /start ni qayta bosing."
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    # Har bir kanal uchun alohida tugma (faqat title bilan)
    for ch in unsubscribed:
        channel_id, link, title, invite_link = ch
        if invite_link:  # Private
            markup.add(types.InlineKeyboardButton(title, url=invite_link))
        else:  # Public
            markup.add(types.InlineKeyboardButton(title, url=f"https://t.me/{link[1:]}"))  # @ belgisini olib tashlash
    markup.add(
        types.InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")
    )
    
    if message_id:
        safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

# Callback query handler
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    add_user(user_id, call.from_user.username, call.from_user.first_name)  # Faollik yangilash
    
    if is_bot_stopped() and not is_admin(user_id):
        handle_bot_stopped(call.message.chat.id, user_id, call.message.message_id)
        return
    
    if call.data == "check_sub":
        subscribed, missing_channel = check_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi! Endi botdan foydalanish.")
            # Start ni qayta ishga tushirish
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🔑 Kod kiritish", callback_data="enter_code"),
                types.InlineKeyboardButton("📺 Kodlar Kanali", url="https://t.me/AniRude1"),
                types.InlineKeyboardButton("👨‍💼 Admin bilan bogʻlanish", url="https://t.me/rude_lxz")
            )
            safe_edit_message_text(bot, f"<b>👋 Assalomu aleykum, {call.from_user.first_name}!</b>\n\n<i>Bu botda hamma turdagi animelar mavjud. Iltimos, anime kodini kiriting.</i>\n📢 <b>Kodlar bor kanalga kiring yoki admin bilan bogʻlaning.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        else:
            bot.answer_callback_query(call.id, f"❌ {missing_channel} kanaliga obuna bo'lmagansiz!")
            show_subscription_prompt(call.message.chat.id, call.message.message_id, missing_channel, user_id)
    elif call.data == "enter_code":
        subscribed, _ = check_subscriptions(user_id)
        if subscribed:
            safe_edit_message_text(bot, "<i>🔑 Anime kodini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
            bot.register_next_step_handler(call.message, process_code)
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id, None, user_id)
    elif call.data.startswith("download_"):
        code = call.data.split("_")[1]
        subscribed, _ = check_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
            anime = cursor.fetchone()
            if anime:
                seasons_count = anime[0]
                markup = types.InlineKeyboardMarkup(row_width=1)
                for s in range(1, seasons_count + 1):
                    markup.add(types.InlineKeyboardButton(f"📺 Fasl {s}", callback_data=f"season_{code}_{s}"))
                bot.send_message(call.message.chat.id, f"<b>🎌 Anime: {code}</b>\n<i>Qaysi faslni koʻrmoqchisiz?</i>", reply_markup=markup, parse_mode='HTML')
            conn.close()
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id, None, user_id)
    elif call.data.startswith("season_"):
        subscribed, _ = check_subscriptions(user_id)
        if subscribed:
            _, code, season_num = call.data.split("_")
            show_season_parts(call.message.chat.id, code, int(season_num), call.message.message_id)
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id, None, user_id)
    elif call.data.startswith("pag_"):
        subscribed, _ = check_subscriptions(user_id)
        if subscribed:
            _, code, season_num, page = call.data.split("_")
            show_season_parts(call.message.chat.id, code, int(season_num), call.message.message_id, int(page))
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id, None, user_id)
    elif call.data.startswith("part_"):
        subscribed, _ = check_subscriptions(user_id)
        if subscribed:
            code, season_num, part_num = call.data.split("_")[1:]
            send_anime_part(call.message.chat.id, code, int(season_num), int(part_num))
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id, None, user_id)
    elif call.data == "close":
        safe_delete_message(bot, call.message.chat.id, call.message.message_id)
    elif call.data == "share":
        # Ulashish - oddiy tugma, funksiya yo'q
        pass
    # Admin callbacklar
    elif call.data == "admin_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Sizda admin huquqi yoʻq!")
            return
        show_admin_panel(call.message.chat.id, call.message.message_id)
    elif call.data == "edit_anime":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>✏️ Tahrirlash uchun anime kodini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, edit_anime_menu)
    elif call.data == "add_anime":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➕ Anime sarlavhasi (rasm va matn bilan yuboring):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, add_anime_header)
    elif call.data == "remove_anime":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➖ Oʻchirish uchun anime kodini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, remove_anime_code)
    elif call.data == "stats":
        if not is_admin(user_id):
            return
        stats_text = get_stats()
        safe_edit_message_text(bot, stats_text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "broadcast":
        if not is_admin(user_id):
            return
        # Yangi markup: Forward va Oddiy xabar
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Forward xabar", callback_data="broadcast_forward"),
            types.InlineKeyboardButton("📝 Oddiy xabar", callback_data="broadcast_text")
        )
        eslatma = "<b>📢 Xabar yuborish tanlovi</b>\n\n<i>Forward yoki Oddiy xabarni tanlang.</i>"
        safe_edit_message_text(bot, eslatma, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "broadcast_forward":
        if not is_admin(user_id):
            return
        set_broadcast_mode(user_id, 'forward')
        safe_edit_message_text(bot, "<i>🔄 Forward qilmoqchi bo'lgan xabarni botga forward qiling (rasm, matn yoki video).</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "broadcast_text":
        if not is_admin(user_id):
            return
        set_broadcast_mode(user_id, 'text')
        # Eslatma qo'shildi
        eslatma = "<b>📢 Xabar yuborish</b>\n\n<i>Namuna uchun /namuna komandasini yozing. Keyin matn, rasm yoki video yuboring (HTML bilan, caption orqali).</i>"
        safe_edit_message_text(bot, eslatma, call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, broadcast_content_handler)
    elif call.data == "list_animes":
        if not is_admin(user_id):
            return
        animes_list = get_animes_list()
        safe_edit_message_text(bot, animes_list, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "manage_channels":
        if not is_admin(user_id):
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("➕ Kanal qoʻshish", callback_data="add_channel"),
            types.InlineKeyboardButton("➖ Kanal oʻchirish", callback_data="remove_channel"),
            types.InlineKeyboardButton("📋 Kanallar roʻyxati", callback_data="list_channels")
        )
        safe_edit_message_text(bot, "<b>📢 Kanallarni boshqarish (majburiy obuna uchun)</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "manage_admins":
        if not is_admin(user_id):
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("➕ Yangi admin qoʻshish", callback_data="add_admin"),
            types.InlineKeyboardButton("➖ Admin oʻchirish", callback_data="remove_admin"),
            types.InlineKeyboardButton("📋 Adminlar roʻyxati", callback_data="list_admins")
        )
        safe_edit_message_text(bot, "<b>👥 Adminlarni boshqarish</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "list_channels":
        if not is_admin(user_id):
            return
        channels_list = get_channels_list()
        safe_edit_message_text(bot, channels_list, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "list_admins":
        if not is_admin(user_id):
            return
        admins_list = get_admins_list()
        safe_edit_message_text(bot, admins_list, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "add_channel":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➕ Kanal uchun inline tugma nomi (title) kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, add_channel_title)
    elif call.data == "remove_channel":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➖ Oʻchirish uchun kanal ID, @username yoki link kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, remove_channel_input)
    elif call.data == "add_admin":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➕ Yangi admin ID sini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, add_admin_id)
    elif call.data == "remove_admin":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➖ Oʻchirish uchun admin ID sini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, remove_admin_id)
    # Yangi: Boshqa sozlamalar
    elif call.data == "other_settings":
        if not is_admin(user_id):
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔧 Bot sozlamasi", callback_data="bot_settings"),
            types.InlineKeyboardButton("🔔 Anime bildirishnomalari", callback_data="anime_notifications"),
            types.InlineKeyboardButton("📁 Bot datasini export qilish", callback_data="export_data")
        )
        markup.add(types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"))
        safe_edit_message_text(bot, "<b>⚙️ Boshqa sozlamalar</b>\n<i>Tanlang:</i>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    # Bot sozlamasi sub-menu
    elif call.data == "bot_settings":
        if not is_admin(user_id):
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("⏹️ Botni toʻxtatish", callback_data="stop_bot"))
        markup.add(types.InlineKeyboardButton("▶️ Botni yoqish", callback_data="start_bot"))
        markup.add(types.InlineKeyboardButton("📊 Bot holati", callback_data="bot_status"))
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        safe_edit_message_text(bot, "<b>🔧 Bot sozlamasi</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "stop_bot":
        if not is_admin(user_id):
            return
        set_bot_stopped(True)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="bot_settings")
        )
        safe_edit_message_text(bot, "<b>✅ Bot toʻxtatildi! Foydalanuvchilar xabarlarga javob bermaydi.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "start_bot":
        if not is_admin(user_id):
            return
        stopped = is_bot_stopped()
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="bot_settings")
        )
        if stopped:
            set_bot_stopped(False)
            safe_edit_message_text(bot, "<b>✅ Bot yoqildi! Foydalanuvchilar normal ishlaydi.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        else:
            safe_edit_message_text(bot, "<b>ℹ️ Bot hali ishlayapti.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "bot_status":
        if not is_admin(user_id):
            return
        stats_text = get_detailed_bot_status()
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="bot_settings")
        )
        safe_edit_message_text(bot, stats_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    # Anime bildirishnomalari sub-menu
    elif call.data == "anime_notifications":
        if not is_admin(user_id):
            return
        settings = get_notification_settings()
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📢 Kanal sozlash", callback_data="set_notification_channel"),
            types.InlineKeyboardButton("🗑️ Kanalni oʻchirish", callback_data="remove_notification_channel")
        )
        markup.add(
            types.InlineKeyboardButton("▶️ Bildirishnomani yoqish", callback_data="enable_notification"),
            types.InlineKeyboardButton("⏹️ Bildirishnomani oʻchirish", callback_data="disable_notification")
        )
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        status_text = f"<b>🔔 Anime bildirishnomalari</b>\n\nStatus: {'Yoqilgan' if settings['enabled'] else 'Oʻchirilgan'}\nKanal: {settings['channel_id'] or 'Sozlanmagan'}"
        safe_edit_message_text(bot, status_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "set_notification_channel":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>📢 Kanal ID yoki @username kiriting (botni kanalga admin qiling!):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, process_notification_channel)
    elif call.data == "remove_notification_channel":
        if not is_admin(user_id):
            return
        set_notification_channel(None)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("▶️ Bildirishnomani yoqish", callback_data="enable_notification"),
            types.InlineKeyboardButton("⏹️ Bildirishnomani oʻchirish", callback_data="disable_notification")
        )
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        safe_edit_message_text(bot, "<b>✅ Bildirishnoma kanali oʻchirildi!</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "enable_notification":
        if not is_admin(user_id):
            return
        settings = get_notification_settings()
        if not settings['channel_id']:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("📢 Kanal sozlash", callback_data="set_notification_channel"))
            markup.add(
                types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
                types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
            )
            safe_edit_message_text(bot, "<b>❌ Avval kanal sozlang! Kanal ID kiriting.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
            return
        set_notification_enabled(True)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🗑️ Kanalni oʻchirish", callback_data="remove_notification_channel"),
            types.InlineKeyboardButton("⏹️ Bildirishnomani oʻchirish", callback_data="disable_notification")
        )
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        safe_edit_message_text(bot, "<b>✅ Bildirishnoma yoqildi! Yangi anime qo'shilganda kanalga yuboriladi.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "disable_notification":
        if not is_admin(user_id):
            return
        settings = get_notification_settings()
        if not settings['enabled']:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📢 Kanal sozlash", callback_data="set_notification_channel"),
                types.InlineKeyboardButton("🗑️ Kanalni oʻchirish", callback_data="remove_notification_channel")
            )
            markup.add(
                types.InlineKeyboardButton("▶️ Bildirishnomani yoqish", callback_data="enable_notification")
            )
            markup.add(
                types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
                types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
            )
            safe_edit_message_text(bot, "<b>ℹ️ Bildirishnoma hali yoqilmagan.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
            return
        set_notification_enabled(False)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📢 Kanal sozlash", callback_data="set_notification_channel"),
            types.InlineKeyboardButton("🗑️ Kanalni oʻchirish", callback_data="remove_notification_channel")
        )
        markup.add(
            types.InlineKeyboardButton("▶️ Bildirishnomani yoqish", callback_data="enable_notification")
        )
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        safe_edit_message_text(bot, "<b>✅ Bildirishnoma oʻchirildi.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    # Export data - tuzatilgan: chat_id ni qabul qilish
    elif call.data == "export_data":
        if not is_admin(user_id):
            return
        export_data(call.message.chat.id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔙 Admin panelga qaytish", callback_data="admin_panel"),
            types.InlineKeyboardButton("⬅️ Orqaga", callback_data="other_settings")
        )
        safe_edit_message_text(bot, "<b>✅ Ma'lumotlar export qilindi! Fayl yuklandi.</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    # Edit anime callbacklar (yangilangan: fasl qo'shish/o'chirish)
    elif call.data.startswith("edit_header_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>✏️ {code} anime uchun yangi sarlavha (rasm va matn bilan yuboring):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: update_anime_header(m, code))
    elif call.data.startswith("edit_name_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>✏️ {code} anime uchun yangi nom kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: update_anime_name(m, code))
    elif call.data.startswith("add_part_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>➕ {code} anime uchun qism qo'shish: Avval fasl raqamini kiriting (masalan: 1).</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: add_part_season(m, code))
    elif call.data.startswith("remove_part_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>➖ {code} anime dan qism o'chirish: Avval fasl raqamini kiriting (masalan: 1).</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: remove_part_season(m, code))
    elif call.data.startswith("replace_part_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>🔄 {code} anime qism videosi almashtirish: Avval fasl raqamini kiriting (masalan: 1).</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: replace_part_season(m, code))
    # Yangi: Fasl qo'shish/o'chirish
    elif call.data.startswith("add_season_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>➕ {code} anime uchun yangi fasl raqamini kiriting (masalan: 3):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: add_season_confirm(m, code))
    elif call.data.startswith("remove_season_"):
        code = call.data.split("_")[2]
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, f"<i>➖ {code} anime dan fasl o'chirish: Fasl raqamini kiriting (masalan: 2):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, lambda m: remove_season_confirm(m, code))

# Yangi handlerlar: Fasl va qism bosqichlari (tuzatilgan: ketma-ket qo'shish)
def add_part_season(message, code):
    if not is_admin(message.from_user.id):
        return
    try:
        season_num = int(message.text.strip())
        bot.send_message(message.chat.id, f"<i>➕ {code} Fasl {season_num} uchun nechta qism qo'shasiz? (masalan: 3)</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_parts_count(m, code, season_num))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri fasl raqami!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_part_season(m, code))

def add_parts_count(message, code, season_num):
    if not is_admin(message.from_user.id):
        return
    try:
        parts_to_add = int(message.text.strip())
        if parts_to_add <= 0:
            raise ValueError
        # Mavjud parts_count ni olish
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT parts_count FROM anime_seasons WHERE code = ? AND season_num = ?', (code, season_num))
        existing = cursor.fetchone()
        if existing:
            current_parts = existing[0]
            start_part = current_parts + 1
        else:
            current_parts = 0
            start_part = 1
            # Yangi season yaratish
            cursor.execute('INSERT INTO anime_seasons (code, season_num, parts_count) VALUES (?, ?, 0)', (code, season_num))
            # Seasons_count ni yangilash
            cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
            seasons = cursor.fetchone()[0]
            if season_num > seasons:
                cursor.execute('UPDATE animes SET seasons_count = ? WHERE code = ?', (season_num, code))
        new_parts_count = current_parts + parts_to_add
        cursor.execute('UPDATE anime_seasons SET parts_count = ? WHERE code = ? AND season_num = ?', (new_parts_count, code, season_num))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} Fasl {season_num} uchun {parts_to_add} ta yangi qism qo'shildi (Qism {start_part} dan boshlab).</b>\n<i>Endi videolarni ketma-ket yuboring (caption bilan).</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, season_num, start_part, new_parts_count, ""))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri son!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_parts_count(m, code, season_num))

def remove_part_season(message, code):
    if not is_admin(message.from_user.id):
        return
    try:
        season_num = int(message.text.strip())
        bot.send_message(message.chat.id, f"<i>➖ {code} Fasl {season_num} dan qism raqamini kiriting (masalan: 5):</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: remove_part_from_anime(m, code, season_num))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri fasl raqami!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: remove_part_season(m, code))

def remove_part_from_anime(message, code, season_num):
    if not is_admin(message.from_user.id):
        return
    try:
        part_num = int(message.text.strip())
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM anime_parts WHERE code = ? AND season_num = ? AND part_num = ?', (code, season_num, part_num))
        if cursor.rowcount > 0:
            cursor.execute('UPDATE anime_seasons SET parts_count = parts_count - 1 WHERE code = ? AND season_num = ?', (code, season_num))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} Fasl {season_num} Qism {part_num} o'chirildi!</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri qism raqami!</b>", parse_mode='HTML')

def replace_part_season(message, code):
    if not is_admin(message.from_user.id):
        return
    try:
        season_num = int(message.text.strip())
        bot.send_message(message.chat.id, f"<i>🔄 {code} Fasl {season_num} dan qism raqamini kiriting (masalan: 5):</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: replace_part_start_with_season(m, code, season_num))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri fasl raqami!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: replace_part_season(m, code))

def replace_part_start_with_season(message, code, season_num):
    if not is_admin(message.from_user.id):
        return
    try:
        part_num = int(message.text.strip())
        bot.send_message(message.chat.id, f"<b>✅ Almashtirish boshlandi. Video va caption yuboring.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: replace_part_video(m, code, season_num, part_num))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri qism raqami!</b>", parse_mode='HTML')

def add_season_confirm(message, code):
    if not is_admin(message.from_user.id):
        return
    try:
        season_num = int(message.text.strip())
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
        current_seasons = cursor.fetchone()[0]
        if season_num <= current_seasons:
            conn.close()
            bot.send_message(message.chat.id, f"<b>❌ Fasl {season_num} allaqachon mavjud! Yangi raqam kiriting.</b>", parse_mode='HTML')
            bot.register_next_step_handler(message, lambda m: add_season_confirm(m, code))
            return
        cursor.execute('UPDATE animes SET seasons_count = ? WHERE code = ?', (season_num, code))
        cursor.execute('INSERT INTO anime_seasons (code, season_num, parts_count) VALUES (?, ?, 0)', (code, season_num))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} uchun Fasl {season_num} qo'shildi! Endi qismlarni qo'shing.</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri fasl raqami!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_season_confirm(m, code))

def remove_season_confirm(message, code):
    if not is_admin(message.from_user.id):
        return
    try:
        season_num = int(message.text.strip())
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT parts_count FROM anime_seasons WHERE code = ? AND season_num = ?', (code, season_num))
        season = cursor.fetchone()
        if not season:
            conn.close()
            bot.send_message(message.chat.id, f"<b>❌ Fasl {season_num} topilmadi!</b>", parse_mode='HTML')
            return
        if season[0] > 0:
            conn.close()
            bot.send_message(message.chat.id, f"<b>❌ Fasl {season_num} da qismlar bor! Avval qismlarni o'chiring.</b>", parse_mode='HTML')
            return
        cursor.execute('DELETE FROM anime_seasons WHERE code = ? AND season_num = ?', (code, season_num))
        cursor.execute('UPDATE animes SET seasons_count = seasons_count - 1 WHERE code = ?', (code,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} dan Fasl {season_num} o'chirildi!</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri fasl raqami!</b>", parse_mode='HTML')

# Join request handler (pending ga saqlash, tasdiqlamasdan)
@bot.chat_join_request_handler()
def handle_join_request(join_request):
    add_pending_join(join_request.from_user.id, join_request.chat.id)

# Forward xabar handler - admin forward qilganda (yuqoriga ko'chirildi)
@bot.message_handler(func=lambda m: m.forward_from or m.forward_from_chat)
def handle_forward_broadcast(message):
    logging.info(f"Forward message received from {message.from_user.id}")
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    mode = get_broadcast_mode(user_id)
    if mode == 'forward':
        logging.info("Broadcasting forward")
        success = send_broadcast_forward(message, user_id)
        bot.send_message(message.chat.id, f"<b>✅ {success} foydalanuvchiga forward qilindi!</b>", parse_mode='HTML')
        # Mode ni tozalash
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM broadcast_mode WHERE admin_id = ?', (user_id,))
        conn.commit()
        conn.close()

# Broadcast content handler (text/photo/video)
def broadcast_content_handler(message):
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return
    mode = get_broadcast_mode(admin_id)
    if mode != 'text':
        return
    
    content = None
    caption = ""
    if message.text:
        content_type = 'text'
        content = message.text.strip()
        if not content:
            bot.send_message(message.chat.id, "<b>❌ Matn bo'sh! Qaytadan yuboring.</b>", parse_mode='HTML')
            bot.register_next_step_handler(message, broadcast_content_handler)
            return
    elif message.photo:
        content_type = 'photo'
        content = message.photo[-1].file_id
        caption = message.caption or ""
        if not caption:
            bot.send_message(message.chat.id, "<b>❌ Rasm uchun caption majburiy! Qaytadan yuboring.</b>", parse_mode='HTML')
            bot.register_next_step_handler(message, broadcast_content_handler)
            return
    elif message.video:
        content_type = 'video'
        content = message.video.file_id
        caption = message.caption or ""
        if not caption:
            bot.send_message(message.chat.id, "<b>❌ Video uchun caption majburiy! Qaytadan yuboring.</b>", parse_mode='HTML')
            bot.register_next_step_handler(message, broadcast_content_handler)
            return
    else:
        bot.send_message(message.chat.id, "<b>❌ Matn, rasm yoki video yuboring!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, broadcast_content_handler)
        return
    
    # Content saqlash
    set_broadcast_content(admin_id, content_type, content, caption)
    
    if message.text and message.text.startswith('/'):
        # Slash komanda bo'lsa, uni admin uchun bajarish (masalan, oddiy xabar)
        bot.send_message(message.chat.id, f"<b>🔧 Komanda '{message.text}' admin uchun bajarildi (broadcast o'tkazilmadi).</b>", parse_mode='HTML')
        bot.send_message(message.chat.id, "<i>Endi inline tugma qo'shish yoki /skip yozing (lekin broadcast bo'lmaydi).</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: broadcast_button_handler(m, None, True))  # True for no broadcast
        return
    
    bot.send_message(message.chat.id, "<i>✅ Content saqlandi! Endi inline tugma qo'shish yoki /skip yozing.</i>\n<b>Namuna:</b> Tugma nomi | url (masalan: 'Kanal' | https://t.me/channel)", parse_mode='HTML')
    bot.register_next_step_handler(message, lambda m: broadcast_button_handler(m, None))

def broadcast_button_handler(message, text, no_broadcast=False):
    admin_id = message.from_user.id
    button_input = message.text.strip()
    markup = None
    if button_input.lower() != '/skip':
        try:
            parts = button_input.split('|')
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(types.InlineKeyboardButton(name, url=url))
            else:
                bot.send_message(message.chat.id, "<b>❌ Noto'g'ri format! Tugma nomi | url</b>", parse_mode='HTML')
                bot.register_next_step_handler(message, lambda m: broadcast_button_handler(m, text, no_broadcast))
                return
        except:
            bot.send_message(message.chat.id, "<b>❌ Xato! /skip yozing.</b>", parse_mode='HTML')
            bot.register_next_step_handler(message, lambda m: broadcast_button_handler(m, text, no_broadcast))
            return
    if no_broadcast:
        bot.send_message(message.chat.id, "<b>✅ Komanda va tugma sozlandi (broadcast o'tkazilmadi).</b>", parse_mode='HTML')
        clear_broadcast_content(admin_id)
    else:
        success = send_broadcast_content(admin_id, markup)
        bot.send_message(message.chat.id, f"<b>✅ {success} foydalanuvchiga xabar yuborildi!</b>", parse_mode='HTML')
        # Mode ni tozalash
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM broadcast_mode WHERE admin_id = ?', (admin_id,))
        conn.commit()
        conn.close()

# Kanal qo'shish bosqichlari
def add_channel_title(message):
    if not is_admin(message.from_user.id):
        return
    title = message.text.strip()
    data = {'title': title}
    bot.send_message(message.chat.id, "<i>📢 Kanal turi: public yoki private? 'public' yoki 'private' yozing.</i>", parse_mode='HTML')
    bot.register_next_step_handler(message, lambda m: add_channel_type(m, data))

def add_channel_type(message, data):
    channel_type = message.text.strip().lower()
    if channel_type not in ['public', 'private']:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri! 'public' yoki 'private' yozing.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_type(m, data))
        return
    data['type'] = channel_type
    if channel_type == 'public':
        bot.send_message(message.chat.id, "<i>@username yoki https://t.me/username kiriting.</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_public(m, data))
    else:
        bot.send_message(message.chat.id, "<i>Private kanal chat_id (masalan: -1001234567890) kiriting.</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_private_id(m, data))

def add_channel_public(message, data):
    link = message.text.strip()
    if not (link.startswith('@') or link.startswith('https://t.me/')):
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri format!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_public(m, data))
        return
    try:
        chat = bot.get_chat(link)
        channel_id = chat.id
        add_channel(channel_id, link, data['title'])
        bot.send_message(message.chat.id, f"<b>✅ Public kanal qo'shildi: {data['title']} - {link}</b>", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"<b>❌ Xato: {e}</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_public(m, data))

def add_channel_private_id(message, data):
    try:
        channel_id = int(message.text.strip())
        bot.send_message(message.chat.id, "<i>Invite link (https://t.me/+...) kiriting:</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_private_link(m, data, channel_id))
    except:
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri ID!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_private_id(m, data))

def add_channel_private_link(message, data, channel_id):
    invite_link = message.text.strip()
    if not invite_link.startswith('https://t.me/+'):
        bot.send_message(message.chat.id, "<b>❌ Noto'g'ri invite link!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_channel_private_link(m, data, channel_id))
        return
    add_channel(channel_id, '', data['title'], invite_link)
    bot.send_message(message.chat.id, f"<b>✅ Private kanal qo'shildi: {data['title']} - ID {channel_id}, Invite: {invite_link}</b>", parse_mode='HTML')

# Notification kanal sozlash
def process_notification_channel(message):
    if not is_admin(message.from_user.id):
        return
    try:
        channel_id_or_username = message.text.strip()
        chat = bot.get_chat(channel_id_or_username)
        channel_id = chat.id
        # Bot admin ekanligini tekshirish
        try:
            bot_member = bot.get_chat_member(channel_id, bot.get_me().id)
            if bot_member.status not in ['administrator', 'creator']:
                bot.send_message(message.chat.id, "<b>❌ Botni kanalga admin qiling! Bot post yubora olmaydi.</b>", parse_mode='HTML')
                return
        except:
            bot.send_message(message.chat.id, "<b>❌ Bot kanal a'zosiga aylana olmadi. Kanalga qo'shing va admin qiling.</b>", parse_mode='HTML')
            return
        set_notification_channel(channel_id)
        bot.send_message(message.chat.id, f"<b>✅ Bildirishnoma kanali sozlandi: {channel_id}</b>\n<i>Endi bildirishnomani yoqing.</i>", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"<b>❌ Xato: {e}. Qaytadan urinib ko'ring.</b>", parse_mode='HTML')

# Anime tahrirlash menyusi (yangilangan: fasl tugmalari qo'shildi)
def edit_anime_menu(message):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM animes WHERE code = ?', (code,))
    anime = cursor.fetchone()
    conn.close()
    if not anime:
        bot.send_message(message.chat.id, "<b>❌ Anime topilmadi!</b>", parse_mode='HTML')
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✏️ Sarlavha tahrirlash", callback_data=f"edit_header_{code}"),
        types.InlineKeyboardButton("✏️ Nom tahrirlash", callback_data=f"edit_name_{code}")
    )
    markup.add(
        types.InlineKeyboardButton("➕ Fasl qo'shish", callback_data=f"add_season_{code}"),
        types.InlineKeyboardButton("➖ Fasl o'chirish", callback_data=f"remove_season_{code}")
    )
    markup.add(
        types.InlineKeyboardButton("➕ Qism qo'shish", callback_data=f"add_part_{code}"),
        types.InlineKeyboardButton("➖ Qism o'chirish", callback_data=f"remove_part_{code}")
    )
    markup.add(types.InlineKeyboardButton("🔄 Video almashtirish", callback_data=f"replace_part_{code}"))
    bot.send_message(message.chat.id, f"<b>✏️ {code} - {anime[0]} ni tahrirlash</b>", reply_markup=markup, parse_mode='HTML')

def update_anime_header(message, code):
    if not is_admin(message.from_user.id):
        return
    if message.photo:
        header_text = message.caption or ""
        header_image_file_id = message.photo[-1].file_id
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE animes SET header = ?, header_image_file_id = ? WHERE code = ?', (header_text, header_image_file_id, code))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} sarlavhasi yangilandi!</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Rasm va matn yuboring!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: update_anime_header(m, code))

def update_anime_name(message, code):
    new_name = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE animes SET name = ? WHERE code = ?', (new_name, code))
    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"<b>✅ {code} nomi yangilandi: {new_name}</b>", parse_mode='HTML')

# Qism qo'shish yangilandi: bo'sh part yaratmasdan, darhol video so'rash (tuzatilgan: ketma-ket, oxiridan davom)
def process_video_upload(message, code, season_num, current_part, parts_count, name):
    if message.video:
        file_id = message.video.file_id
        caption = message.caption or ""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Part mavjudligini tekshirish, yo'q bo'lsa qo'shish
        cursor.execute('SELECT id FROM anime_parts WHERE code = ? AND season_num = ? AND part_num = ?', (code, season_num, current_part))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO anime_parts (code, season_num, part_num, file_id, caption) VALUES (?, ?, ?, ?, ?)',
                           (code, season_num, current_part, file_id, caption))
        else:
            cursor.execute('UPDATE anime_parts SET file_id = ?, caption = ? WHERE code = ? AND season_num = ? AND part_num = ?',
                           (file_id, caption, code, season_num, current_part))
        conn.commit()
        conn.close()
        
        if current_part < parts_count:
            remaining = parts_count - current_part
            bot.send_message(message.chat.id, f"<b>✅ Fasl {season_num}, Qism {current_part} yuklandi!</b>\n<i>Qolgan {remaining} qismni yuboring.</i>", parse_mode='HTML')
            bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, season_num, current_part + 1, parts_count, name))
        else:
            bot.send_message(message.chat.id, "<b>🎉 Fasl to'liq yuklandi!</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Video yuborish majburiy! Qaytadan urinib ko'ring yoki /cancel yozing.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, season_num, current_part, parts_count, name))

def send_anime_notification(code, name, adding_admin_id):
    settings = get_notification_settings()
    if not settings['enabled'] or not settings['channel_id']:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT upload_date, header, header_image_file_id FROM animes WHERE code = ?', (code,))
    anime_info = cursor.fetchone()
    if not anime_info:
        conn.close()
        return
    upload_date, header, header_image_file_id = anime_info
    # Bot nomi
    bot_name = bot.get_me().first_name
    # Admin nomi
    cursor.execute('SELECT first_name FROM users WHERE user_id = ?', (adding_admin_id,))
    admin_result = cursor.fetchone()
    admin_name = admin_result[0] if admin_result else "Noma'lum admin"
    conn.close()
    
    text = f"<b>🎌 Yangi anime qo'shildi!</b>\n\n"
    text += f"1. <b>Nomi:</b> {name}\n"
    text += f"2. <b>Kodi:</b> <code>{code}</code>\n"
    text += f"3. <b>Qo'shilgan sana:</b> {upload_date}\n"
    text += f"4. <b>Qo'shgan admin:</b> {admin_name}\n"
    text += f"5. <b>Bot useri:</b> {bot_name}"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📥 Yuklab olish", url=f"https://t.me/{bot.get_me().username}?start={code}"))
    
    try:
        if header_image_file_id:
            bot.send_photo(settings['channel_id'], header_image_file_id, caption=text, reply_markup=markup, parse_mode='HTML')
        else:
            bot.send_message(settings['channel_id'], text, reply_markup=markup, parse_mode='HTML')
        logging.info(f"Bildirishnoma muvaffaqiyatli yuborildi: {code}")
    except Exception as e:
        logging.error(f"Bildirishnoma xatosi {code}: {e}")

# Qism yuborish yangilandi: xatolik uchun log va yaxshi xabar
def send_anime_part(chat_id, code, season_num, part_num):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, caption FROM anime_parts WHERE code = ? AND season_num = ? AND part_num = ?',
                   (code, season_num, part_num))
    part = cursor.fetchone()
    conn.close()
    
    if part:
        file_id, caption = part
        if file_id:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📤 Doʻstlarga ulashish", switch_inline_query="Anime qismi"),
                types.InlineKeyboardButton("❌ Yopish", callback_data="close")
            )
            bot.send_video(chat_id, file_id, caption=caption, reply_markup=markup, parse_mode='HTML')
        else:
            logging.warning(f"Video yuklanmagan: {code} Fasl {season_num} Qism {part_num}")  # Log qo'shildi
            bot.send_message(chat_id, f"<b>⚠️ {code} Fasl {season_num} Qism {part_num} yuklanmoqda... Admin bilan bog'laning yoki keyinroq urinib ko'ring.</b>", parse_mode='HTML')
    else:
        bot.send_message(chat_id, "<b>❌ Qism topilmadi! Admin bilan bog'laning.</b>", parse_mode='HTML')

def show_season_parts(chat_id, code, season_num, message_id=None, page=0):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT parts_count FROM anime_seasons WHERE code = ? AND season_num = ?', (code, season_num))
    season = cursor.fetchone()
    if not season:
        bot.send_message(chat_id, "<b>❌ Fasl topilmadi!</b>", parse_mode='HTML')
        conn.close()
        return
    parts_count = season[0]
    conn.close()
    
    items_per_page = 24
    total_pages = (parts_count + items_per_page - 1) // items_per_page
    start = page * items_per_page
    end = min(start + items_per_page, parts_count)
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for i in range(start + 1, end + 1):
        buttons.append(types.InlineKeyboardButton(f"📺 Qism {i}", callback_data=f"part_{code}_{season_num}_{i}"))
    markup.add(*buttons)
    
    # Pagination tugmalari
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(types.InlineKeyboardButton("⬅️ Oldingi", callback_data=get_pagination_callback(code, season_num, page - 1)))
        nav_row.append(types.InlineKeyboardButton("❌ Yopish", callback_data="close"))
        if page < total_pages - 1:
            nav_row.append(types.InlineKeyboardButton("➡️ Keyingi", callback_data=get_pagination_callback(code, season_num, page + 1)))
        markup.row(*nav_row)
    
    text = f"<b>🎌 Anime: {code} - Fasl {season_num}</b>\n<i>Qaysi qismni koʻrmoqchisiz? (Sahifa {page + 1}/{total_pages})</i>"
    
    if message_id:
        safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

# Admin panel ko'rsatish (yangilangan: Boshqa sozlamalar qo'shildi)
def show_admin_panel(chat_id, message_id):
    greeting = f"<b>🎛️ Salom, admin! Panelga xush kelibsiz</b>"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("✏️ Anime tahrirlash", callback_data="edit_anime"))
    markup.add(
        types.InlineKeyboardButton("➕ Anime qo'shish", callback_data="add_anime"),
        types.InlineKeyboardButton("➖ Anime o'chirish", callback_data="remove_anime")
    )
    markup.add(types.InlineKeyboardButton("📢 Xabar yuborish", callback_data="broadcast"))
    markup.add(
        types.InlineKeyboardButton("📊 Statistikalar", callback_data="stats"),
        types.InlineKeyboardButton("📚 Animelar ro'yxati", callback_data="list_animes")
    )
    markup.add(
        types.InlineKeyboardButton("📢 Kanallar", callback_data="manage_channels"),
        types.InlineKeyboardButton("👥 Adminlar", callback_data="manage_admins")
    )
    markup.add(types.InlineKeyboardButton("⚙️ Boshqa sozlamalar", callback_data="other_settings"))
    
    safe_edit_message_text(bot, greeting, chat_id, message_id, reply_markup=markup, parse_mode='HTML')

# /admin komandasi
@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "<b>❌ Sizda admin huquqi yoʻq!</b>", parse_mode='HTML')
        return
    
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎛️ Admin Panel", callback_data="admin_panel"))
    bot.send_message(message.chat.id, "<b>👨‍💼 Admin panel ochildi</b>", reply_markup=markup, parse_mode='HTML')

# Kanal o'chirish yangilandi: identifier bilan
def remove_channel_input(message):
    if not is_admin(message.from_user.id):
        return
    identifier = message.text.strip()
    deleted = delete_channel_by_identifier(identifier)
    if deleted:
        bot.send_message(message.chat.id, f"<b>✅ Kanal {identifier} o'chirildi!</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Kanal topilmadi!</b>", parse_mode='HTML')

# Kod kiritish (tuzatilgan: bot stopped tekshiruvi)
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if is_bot_stopped() and not is_admin(message.from_user.id):
        handle_bot_stopped(message.chat.id, message.from_user.id)
        return
    # Boshqa message handlerlar...

def process_code(message):
    if is_bot_stopped() and not is_admin(message.from_user.id):
        handle_bot_stopped(message.chat.id, message.from_user.id)
        return
    subscribed, _ = check_subscriptions(message.from_user.id)
    if not subscribed:
        show_subscription_prompt(message.chat.id, None, None, message.from_user.id)
        return
    
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT name, seasons_count, header, header_image_file_id FROM animes WHERE code = ?', (code,))
    anime = cursor.fetchone()
    conn.close()
    
    if anime:
        name, seasons_count, header, header_image_file_id = anime
        if header_image_file_id:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("📥 Yuklab olish", callback_data=f"download_{code}"))
            bot.send_photo(message.chat.id, header_image_file_id, caption=header or f"<b>🎌 Anime: {code}</b>", reply_markup=markup, parse_mode='HTML')
        elif header:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("📥 Yuklab olish", callback_data=f"download_{code}"))
            bot.send_message(message.chat.id, header, reply_markup=markup, parse_mode='HTML')
        else:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for s in range(1, seasons_count + 1):
                markup.add(types.InlineKeyboardButton(f"📺 Fasl {s}", callback_data=f"season_{code}_{s}"))
            bot.send_message(message.chat.id, f"<b>🎌 Anime: {code}</b>\n<i>Qaysi faslni koʻrmoqchisiz?</i>", reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Bunday kod topilmadi. Qaytadan urinib koʻring.</b>", parse_mode='HTML')

# Anime o'chirish
def remove_anime_code(message):
    if not is_admin(message.from_user.id):
        return
    
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM animes WHERE code = ?', (code,))
    cursor.execute('DELETE FROM anime_seasons WHERE code = ?', (code,))
    cursor.execute('DELETE FROM anime_parts WHERE code = ?', (code,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    if deleted:
        bot.send_message(message.chat.id, f"<b>✅ Anime <code>{code}</code> oʻchirildi!</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Kod topilmadi!</b>", parse_mode='HTML')

# Statistikalar (oddiy)
def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Foydalanuvchilar soni
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    
    # Animelar soni
    cursor.execute('SELECT COUNT(*) FROM animes')
    animes_count = cursor.fetchone()[0]
    
    # Oylik foydalanuvchilar
    month_ago = (datetime.now() - timedelta(days=30)).date()
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE activity_date >= ?', (month_ago,))
    monthly_users = cursor.fetchone()[0]
    
    # Haftalik
    week_ago = (datetime.now() - timedelta(days=7)).date()
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE activity_date >= ?', (week_ago,))
    weekly_users = cursor.fetchone()[0]
    
    conn.close()
    
    return f"""<b>📊 Statistikalar</b>

👥 <b>Foydalanuvchilar:</b> {users_count}
🎌 <b>Animelar:</b> {animes_count}
📅 <b>Oylik faol:</b> {monthly_users}
📆 <b>Haftalik faol:</b> {weekly_users}"""

# Batafsil bot holati
def get_detailed_bot_status():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Foydalanuvchilar soni
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    
    # Animelar soni
    cursor.execute('SELECT COUNT(*) FROM animes')
    animes_count = cursor.fetchone()[0]
    
    # Fasllar soni
    cursor.execute('SELECT SUM(parts_count) FROM anime_seasons')
    total_parts = cursor.fetchone()[0] or 0
    
    # Oylik foydalanuvchilar
    month_ago = (datetime.now() - timedelta(days=30)).date()
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE activity_date >= ?', (month_ago,))
    monthly_users = cursor.fetchone()[0]
    
    # Haftalik
    week_ago = (datetime.now() - timedelta(days=7)).date()
    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE activity_date >= ?', (week_ago,))
    weekly_users = cursor.fetchone()[0]
    
    # Bot holati
    stopped = is_bot_stopped()
    settings = get_notification_settings()
    notif_status = "Yoqilgan" if settings['enabled'] else "Oʻchirilgan"
    
    conn.close()
    
    return f"""<b>📊 Bot holati (toʻliq statistika)</b>

🔧 <b>Bot ish holati:</b> {'Toʻxtatilgan' if stopped else 'Ishlayapti'}
🔔 <b>Bildirishnoma:</b> {notif_status}

👥 <b>Foydalanuvchilar:</b> {users_count}
🎌 <b>Animelar:</b> {animes_count}
📦 <b>Jami qismlar:</b> {total_parts}
📅 <b>Oylik faol:</b> {monthly_users}
📆 <b>Haftalik faol:</b> {weekly_users}"""

# Export funksiyasi (tuzatilgan: chat_id qabul qilish)
def export_data(chat_id):
    conn = sqlite3.connect(DB_NAME)
    # Barcha jadvallarni export
    tables = ['users', 'admins', 'channels', 'animes', 'anime_seasons', 'anime_parts', 'user_activity', 'bot_settings']
    data = {}
    for table in tables:
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM {table}')
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        data[table] = [dict(zip(columns, row)) for row in rows]
    
    conn.close()
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    file_io = StringIO(json_data)
    bot.send_document(chat_id, document=types.InputFile(file_io, 'bot_data_export.json'), caption="📁 Bot ma'lumotlari export (JSON)")

# Admin qo'shish/o'chirish (tuzatilgan: asosiy admin o'chirilmaydi)
def add_admin_id(message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        admin_id = int(message.text.strip())
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO admins (admin_id) VALUES (?)', (admin_id,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ Admin <code>{admin_id}</code> qo'shildi!</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri ID!</b>", parse_mode='HTML')

def remove_admin_id(message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        admin_id = int(message.text.strip())
        if admin_id == DEFAULT_ADMIN_ID:
            bot.send_message(message.chat.id, "<b>❌ Asosiy adminni oʻchirib boʻlmaydi!</b>", parse_mode='HTML')
            return
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM admins WHERE admin_id = ?', (admin_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        if deleted:
            bot.send_message(message.chat.id, f"<b>✅ Admin <code>{admin_id}</code> oʻchirildi!</b>", parse_mode='HTML')
        else:
            bot.send_message(message.chat.id, "<b>❌ Admin topilmadi!</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri ID!</b>", parse_mode='HTML')

# Kanallar ro'yxati
def get_channels_list():
    channels = get_channels()
    if channels:
        list_text = "<b>📢 Majburiy obuna kanallari:</b>\n\n"
        for c in channels:
            channel_id, link, title, invite_link = c
            if invite_link:
                list_text += f"• <b>{title}</b> - {invite_link}\n"
            else:
                list_text += f"• <b>{title}</b> - {link}\n"
    else:
        list_text = "<b>❌ Kanallar yoʻq.</b>"
    return list_text

# Adminlar ro'yxati
def get_admins_list():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT admin_id FROM admins')
    admins = cursor.fetchall()
    conn.close()
    if admins:
        list_text = "<b>👥 Adminlar roʻyxati:</b>\n\n" + "\n".join([f"• <code>{a[0]}</code>" for a in admins])
    else:
        list_text = "<b>❌ Adminlar yoʻq.</b>"
    return list_text

# Animelar ro'yxati
def get_animes_list():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT code, name FROM animes')
    animes = cursor.fetchall()
    conn.close()
    if animes:
        list_text = "<b>📚 Animelar roʻyxati:</b>\n\n" + "\n".join([f"• <code>{a[0]}</code> - {a[1]}" for a in animes])
    else:
        list_text = "<b>❌ Animelar yoʻq.</b>"
    return list_text

# Anime qo'shish yangi usul: sarlavha bilan (tuzatilgan: admin_id o'tkazish bildirishnoma uchun)
def add_anime_header(message):
    if not is_admin(message.from_user.id):
        return
    if message.photo:
        header_text = message.caption or ""
        header_image_file_id = message.photo[-1].file_id
        admin_id = message.from_user.id
        msg = bot.send_message(message.chat.id, "<i>📝 Anime kodini kiriting:</i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: add_anime_code_with_header(m, header_text, header_image_file_id, admin_id))
    else:
        bot.send_message(message.chat.id, "<b>❌ Sarlavha uchun rasm va matn yuboring!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, add_anime_header)

def add_anime_code_with_header(message, header_text, header_image_file_id, admin_id):
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM animes WHERE code = ?', (code,))
    if cursor.fetchone():
        bot.send_message(message.chat.id, "<b>❌ Bunday kod allaqachon mavjud!</b>", parse_mode='HTML')
        conn.close()
        return
    conn.close()
    
    msg = bot.send_message(message.chat.id, "<i>📊 Necha fasl yuklaysiz? (Agar faslsiz boʻlsa /skip yozing)</i>", parse_mode='HTML')
    bot.register_next_step_handler(msg, lambda m: add_anime_seasons(m, code, header_text, header_image_file_id, admin_id))

def add_anime_seasons(message, code, header_text, header_image_file_id, admin_id):
    if message.text.strip().lower() == '/skip':
        seasons_count = 1
        msg = bot.send_message(message.chat.id, "<i>📊 Necha qism yuklaysiz?</i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: add_season_parts(m, code, 1, seasons_count, header_text, header_image_file_id, True, admin_id))
        return
    
    try:
        seasons_count = int(message.text.strip())
        if seasons_count <= 0:
            raise ValueError
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri son! Qaytadan urinib koʻring yoki /skip yozing.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_anime_seasons(m, code, header_text, header_image_file_id, admin_id))
        return
    
    bot.send_message(message.chat.id, f"<b>✅ Fasllar soni: {seasons_count}</b>\n<i>Fasl 1 uchun nechta qism yuklaysiz?</i>", parse_mode='HTML')
    bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, 1, seasons_count, header_text, header_image_file_id, False, admin_id))

def add_season_parts(message, code, current_season, seasons_count, header_text, header_image_file_id, skip, admin_id):
    try:
        parts_count = int(message.text.strip())
        if parts_count <= 0:
            raise ValueError
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri son! Qaytadan urinib koʻring.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, current_season, seasons_count, header_text, header_image_file_id, skip, admin_id))
        return
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO anime_seasons (code, season_num, parts_count) VALUES (?, ?, ?)',
                   (code, current_season, parts_count))
    conn.commit()
    conn.close()
    
    if current_season < seasons_count:
        next_season = current_season + 1
        bot.send_message(message.chat.id, f"<b>✅ Fasl {current_season} uchun {parts_count} qism saqlandi!</b>\n<i>Fasl {next_season} uchun nechta qism yuklaysiz?</i>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, next_season, seasons_count, header_text, header_image_file_id, skip, admin_id))
    else:
        msg = bot.send_message(message.chat.id, "<i>📝 Anime nomini kiriting (faqat roʻyxat uchun):</i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: add_anime_name(m, code, seasons_count, header_text, header_image_file_id, skip, admin_id))

def add_anime_name(message, code, seasons_count, header_text, header_image_file_id, skip, admin_id):
    name = message.text.strip()
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO animes (code, name, seasons_count, upload_date, header, header_image_file_id) VALUES (?, ?, ?, ?, ?, ?)',
                   (code, name, seasons_count, date.today(), header_text, header_image_file_id))
    conn.commit()
    conn.close()
    
    bot.send_message(message.chat.id, "<b>✅ Anime ma'lumotlari saqlandi!</b>\n<i>Endi qismlarni yuklang. Fasl 1, Qism 1 dan boshlab ketma-ket yuboring (video + matn bilan).</i>", parse_mode='HTML')
    # Birinchi faslning qismlar sonini olish
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT parts_count FROM anime_seasons WHERE code = ? AND season_num = 1', (code,))
    first_parts = cursor.fetchone()[0]
    conn.close()
    bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, 1, 1, first_parts, name))
    # Bildirishnoma yuborish
    send_anime_notification(code, name, admin_id)

def replace_part_video(message, code, season_num, part_num):
    if message.video:
        file_id = message.video.file_id
        caption = message.caption or ""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE anime_parts SET file_id = ?, caption = ? WHERE code = ? AND season_num = ? AND part_num = ?', (file_id, caption, code, season_num, part_num))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ {code} Fasl {season_num} Qism {part_num} videosi almashtirildi!</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Video yuboring!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: replace_part_video(m, code, season_num, part_num))

# Robust polling: xatolikda qayta ishga tushirish
def start_polling():
    while True:
        try:
            print("🤖 Bot ishga tushdi...")
            logging.info("Bot polling boshlandi...")
            bot.polling(
                none_stop=True,
                interval=0,  # Tezlik uchun interval 0
                timeout=60,  # Request timeout 60 soniya (oldingi 25 dan ko'p)
                long_polling_timeout=30  # Telegram long poll timeout 30 soniya
            )
        except Exception as e:
            logging.error(f"Polling xatosi: {e}")
            print(f"Xato: {e}. 10 soniya kutib, qayta urinish...")
            time.sleep(10)  # 10 soniya kutish

# Botni ishga tushirish
if __name__ == '__main__':
    start_polling()