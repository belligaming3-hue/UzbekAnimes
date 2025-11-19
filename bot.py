import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta, date
import logging

# Logging sozlash
logging.basicConfig(level=logging.INFO)

# Bot tokenini o'zingiznikiga almashtiring
BOT_TOKEN = '8050815676:AAF8RPwoLCqpzaC4-4EjKwCWbkQzpAYutFg
bot = telebot.TeleBot(BOT_TOKEN)

# Ma'lumotlar bazasini yaratish
DB_NAME = 'anime_bot.db'

# Majburiy kanal (yangi anime xabari faqat shu kanalga yuboriladi)
REQUIRED_CHANNEL = '@AniRude1'

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
    
    # Kanal jadvali (faqat majburiy obuna uchun)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY
        )
    ''')
    
    # Anime jadvali: kod, nom, fasllar soni, yuklash vaqti
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS animes (
            code TEXT PRIMARY KEY,
            name TEXT,
            seasons_count INTEGER,
            upload_date DATE
        )
    ''')
    
    # seasons_count ustunini qo'shish agar mavjud bo'lmasa
    cursor.execute("PRAGMA table_info(animes)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'seasons_count' not in columns:
        cursor.execute("ALTER TABLE animes ADD COLUMN seasons_count INTEGER DEFAULT 1")
        logging.info("Seasons_count ustuni qo'shildi.")
    
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
    
    # Dastlabki adminni qo'shish
    default_admin = 5668810530
    cursor.execute('INSERT OR IGNORE INTO admins (admin_id) VALUES (?)', (default_admin,))
    
    # Majburiy kanal qo'shish (agar yo'q bo'lsa)
    cursor.execute('INSERT OR IGNORE INTO channels (channel_id) VALUES (?)', (REQUIRED_CHANNEL,))
    
    conn.commit()
    conn.close()

init_db()

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

# Barcha kanallarga obuna tekshirish (majburiy obuna uchun)
def check_all_subscriptions(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id FROM channels')
    channels = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    for channel in channels:
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False, channel
        except Exception as e:
            logging.error(f"Obuna tekshirish xatosi {channel}: {e}")
            return False, channel
    return True, None

# Admin tekshirish
def is_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE admin_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Yangi anime xabari faqat belgilangan kanalga yuborish (REQUIRED_CHANNEL)
def send_to_required_channel(code, name, seasons_count):
    try:
        bot_username = bot.get_me().username
        text = f"<b>🎌 Yangi anime qo'shildi!</b>\n\n📝 <b>Nomi:</b> {name}\n🔑 <b>Kod:</b> <code>{code}</code>\n📊 <b>Fasllar soni:</b> {seasons_count}"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📥 Yuklab olish", url=f"https://t.me/{bot_username}?start={code}"))
        
        bot.send_message(REQUIRED_CHANNEL, text, reply_markup=markup, parse_mode='HTML')
        logging.info(f"Xabar yuborildi: {REQUIRED_CHANNEL}")
    except Exception as e:
        logging.error(f"Kanalga yuborish xatosi {REQUIRED_CHANNEL}: {e}")

# Xavfsiz edit_message_text
def safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=None, parse_mode=None):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 400 and ("message is not modified" in e.description or "message can't be edited" in e.description):
            # Agar edit bo'lmasa, yangi xabar yuborish
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

# /start komandasi (deep link bilan)
@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    add_user(user_id, username, first_name)
    
    if len(message.text.split()) > 1:
        # Deep link: kod bilan start
        code = message.text.split()[1]
        subscribed, missing_channel = check_all_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            # Fasllar ro'yxati
            cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
            anime = cursor.fetchone()
            if anime:
                seasons_count = anime[0]
                markup = types.InlineKeyboardMarkup(row_width=1)
                for s in range(1, seasons_count + 1):
                    markup.add(types.InlineKeyboardButton(f"📺 Fasl {s}", callback_data=f"season_{code}_{s}"))
                bot.send_message(message.chat.id, f"<b>🎌 Anime: {code}</b>\n<i>Qaysi faslni koʻrmoqchisiz?</i>", reply_markup=markup, parse_mode='HTML')
            conn.close()
            return
        else:
            # Obuna talab qilish (yangi xabar yuborish)
            show_subscription_prompt(message.chat.id, None, missing_channel)
            return
    else:
        # Oddiy start
        subscribed, missing_channel = check_all_subscriptions(user_id)
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
            # Obuna talab qilish (yangi xabar yuborish)
            show_subscription_prompt(message.chat.id, None, missing_channel)

def show_subscription_prompt(chat_id, message_id, missing_channel=None):
    if missing_channel:
        text = f"<b>🔒 Majburiy obuna!</b>\n\n<i>Botdan foydalanish uchun <b>{missing_channel}</b> kanaliga obuna boʻling.</i>\n\nObuna boʻlgandan keyin /start ni qayta bosing."
    else:
        text = f"<b>🔒 Majburiy obuna!</b>\n\n<i>Barcha kanallarga obuna boʻling.</i>\n\nObuna boʻlgandan keyin /start ni qayta bosing."
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Kanallar roʻyxati", callback_data="sub_channels_list"),
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
    
    if call.data == "check_sub":
        subscribed, missing_channel = check_all_subscriptions(user_id)
        if subscribed:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET subscribed = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi! Endi botdan foydalaning.")
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
            show_subscription_prompt(call.message.chat.id, call.message.message_id, missing_channel)
    elif call.data == "sub_channels_list":
        channels_text = get_channels_list()
        safe_edit_message_text(bot, channels_text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    elif call.data == "enter_code":
        subscribed, _ = check_all_subscriptions(user_id)
        if subscribed:
            safe_edit_message_text(bot, "<i>🔑 Anime kodini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
            bot.register_next_step_handler(call.message, process_code)
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("season_"):
        subscribed, _ = check_all_subscriptions(user_id)
        if subscribed:
            _, code, season_num = call.data.split("_")
            show_season_parts(call.message.chat.id, code, int(season_num), call.message.message_id)
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("pag_"):
        subscribed, _ = check_all_subscriptions(user_id)
        if subscribed:
            _, code, season_num, page = call.data.split("_")
            show_season_parts(call.message.chat.id, code, int(season_num), call.message.message_id, int(page))
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("part_"):
        subscribed, _ = check_all_subscriptions(user_id)
        if subscribed:
            code, season_num, part_num = call.data.split("_")[1:]
            send_anime_part(call.message.chat.id, code, int(season_num), int(part_num))
        else:
            show_subscription_prompt(call.message.chat.id, call.message.message_id)
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
    elif call.data == "add_anime":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➕ Anime kodini kiriting:</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, add_anime_code)
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
    elif call.data == "manage_admins":
        if not is_admin(user_id):
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("➕ Yangi admin qoʻshish", callback_data="add_admin"),
            types.InlineKeyboardButton("➖ Admin oʻchirish", callback_data="remove_admin")
        )
        safe_edit_message_text(bot, "<b>👥 Adminlarni boshqarish</b>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    elif call.data == "list_admins":
        if not is_admin(user_id):
            return
        admins_list = get_admins_list()
        safe_edit_message_text(bot, admins_list, call.message.chat.id, call.message.message_id, parse_mode='HTML')
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
    elif call.data == "add_channel":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➕ Kanal username kiriting (@username):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, add_channel_username)
    elif call.data == "remove_channel":
        if not is_admin(user_id):
            return
        safe_edit_message_text(bot, "<i>➖ Oʻchirish uchun kanal username kiriting (@username):</i>", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        bot.register_next_step_handler(call.message, remove_channel_username)
    elif call.data == "list_channels":
        if not is_admin(user_id):
            return
        channels_list = get_channels_list()
        safe_edit_message_text(bot, channels_list, call.message.chat.id, call.message.message_id, parse_mode='HTML')
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

# Fasllar ro'yxati ko'rsatish
def show_seasons_list(chat_id, code, message_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
    anime = cursor.fetchone()
    conn.close()
    
    if anime:
        seasons_count = anime[0]
        markup = types.InlineKeyboardMarkup(row_width=1)
        for s in range(1, seasons_count + 1):
            markup.add(types.InlineKeyboardButton(f"📺 Fasl {s}", callback_data=f"season_{code}_{s}"))
        
        text = f"<b>🎌 Anime: {code}</b>\n<i>Qaysi faslni koʻrmoqchisiz?</i>"
        
        if message_id:
            safe_edit_message_text(bot, text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, "<b>❌ Anime topilmadi!</b>", parse_mode='HTML')

# Fasl qismlarini ko'rsatish (pagination bilan)
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

# Anime qismini yuborish
def send_anime_part(chat_id, code, season_num, part_num):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, caption FROM anime_parts WHERE code = ? AND season_num = ? AND part_num = ?',
                   (code, season_num, part_num))
    part = cursor.fetchone()
    conn.close()
    
    if part:
        file_id, caption = part
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📤 Doʻstlarga ulashish", switch_inline_query="Anime qismi"),
            types.InlineKeyboardButton("❌ Yopish", callback_data="close")
        )
        bot.send_video(chat_id, file_id, caption=caption, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(chat_id, "<b>❌ Qism topilmadi!</b>", parse_mode='HTML')

# Admin panel ko'rsatish
def show_admin_panel(chat_id, message_id):
    greeting = f"<b>🎛️ Salom, admin! Panelga xush kelibsiz</b>"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Anime qoʻshish", callback_data="add_anime"),
        types.InlineKeyboardButton("➖ Anime oʻchirish", callback_data="remove_anime"),
        types.InlineKeyboardButton("📊 Statistikalar", callback_data="stats"),
        types.InlineKeyboardButton("👥 Admin qoʻshish/oʻchirish", callback_data="manage_admins"),
        types.InlineKeyboardButton("📢 Kanal qoʻshish/oʻchirish", callback_data="manage_channels"),
        types.InlineKeyboardButton("📋 Adminlar roʻyxati", callback_data="list_admins"),
        types.InlineKeyboardButton("📚 Animelar roʻyxati", callback_data="list_animes")
    )
    
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

# /animelar komandasi
@bot.message_handler(commands=['animelar'])
def animelar_command(message):
    if not is_admin(message.from_user.id):
        return
    
    msg = bot.send_message(message.chat.id, "<i>🔗 Anime kodini kiriting (ulashish linki uchun):</i>", parse_mode='HTML')
    bot.register_next_step_handler(msg, generate_share_link)

# Kod kiritish
def process_code(message):
    subscribed, _ = check_all_subscriptions(message.from_user.id)
    if not subscribed:
        show_subscription_prompt(message.chat.id, None)
        return
    
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT name, seasons_count FROM animes WHERE code = ?', (code,))
    anime = cursor.fetchone()
    conn.close()
    
    if anime:
        name, seasons_count = anime
        show_seasons_list(message.chat.id, code)
    else:
        bot.send_message(message.chat.id, "<b>❌ Bunday kod topilmadi. Qaytadan urinib koʻring.</b>", parse_mode='HTML')

# Anime qo'shish
def add_anime_code(message):
    if not is_admin(message.from_user.id):
        return
    
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
    bot.register_next_step_handler(msg, lambda m: add_anime_seasons(m, code))

def add_anime_seasons(message, code):
    if message.text.strip().lower() == '/skip':
        seasons_count = 1
        msg = bot.send_message(message.chat.id, "<i>📊 Necha qism yuklaysiz?</i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: add_season_parts(m, code, 1, seasons_count, None, skip=True))
        return
    
    try:
        seasons_count = int(message.text.strip())
        if seasons_count <= 0:
            raise ValueError
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri son! Qaytadan urinib koʻring yoki /skip yozing.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_anime_seasons(m, code))
        return
    
    bot.send_message(message.chat.id, f"<b>✅ Fasllar soni: {seasons_count}</b>\n<i>Fasl 1 uchun nechta qism yuklaysiz?</i>", parse_mode='HTML')
    bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, 1, seasons_count, None, skip=False))

def add_season_parts(message, code, current_season, seasons_count, name, skip):
    try:
        parts_count = int(message.text.strip())
        if parts_count <= 0:
            raise ValueValueError
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri son! Qaytadan urinib koʻring.</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, current_season, seasons_count, name, skip))
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
        bot.register_next_step_handler(message, lambda m: add_season_parts(m, code, next_season, seasons_count, name, skip))
    else:
        msg = bot.send_message(message.chat.id, "<i>📝 Anime nomini kiriting (faqat roʻyxat uchun):</i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, lambda m: add_anime_name(m, code, seasons_count, skip))

def add_anime_name(message, code, seasons_count, skip):
    name = message.text.strip()
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO animes (code, name, seasons_count, upload_date) VALUES (?, ?, ?, ?)',
                   (code, name, seasons_count, date.today()))
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

def process_video_upload(message, code, season_num, current_part, parts_count, name):
    if message.video:
        file_id = message.video.file_id
        caption = message.caption or ""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO anime_parts (code, season_num, part_num, file_id, caption) VALUES (?, ?, ?, ?, ?)',
                       (code, season_num, current_part, file_id, caption))
        conn.commit()
        conn.close()
        
        if current_part < parts_count:
            remaining = parts_count - current_part
            bot.send_message(message.chat.id, f"<b>✅ Fasl {season_num}, Qism {current_part} yuklandi!</b>\n<i>Qolgan {remaining} qismni yuboring.</i>", parse_mode='HTML')
            bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, season_num, current_part + 1, parts_count, name))
        else:
            # Keyingi faslni tekshirish
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT season_num, parts_count FROM anime_seasons WHERE code = ? AND season_num > ? ORDER BY season_num LIMIT 1', (code, season_num))
            next_season = cursor.fetchone()
            conn.close()
            
            if next_season:
                next_season_num, next_parts = next_season
                bot.send_message(message.chat.id, f"<b>✅ Fasl {season_num} to'liq yuklandi!</b>\n<i>Fasl {next_season_num}, Qism 1 ni yuboring ({next_parts} ta qism).</i>", parse_mode='HTML')
                bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, next_season_num, 1, next_parts, name))
            else:
                bot.send_message(message.chat.id, "<b>🎉 Anime muvaffaqiyatli qoʻshildi!</b>", parse_mode='HTML')
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute('SELECT seasons_count FROM animes WHERE code = ?', (code,))
                seasons_count = cursor.fetchone()[0]
                conn.close()
                send_to_required_channel(code, name, seasons_count)
    else:
        bot.send_message(message.chat.id, "<b>❌ Faqat video yuboring!</b>", parse_mode='HTML')
        bot.register_next_step_handler(message, lambda m: process_video_upload(m, code, season_num, current_part, parts_count, name))

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

# Statistikalar
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

# Admin qo'shish/o'chirish
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
        bot.send_message(message.chat.id, f"<b>✅ Admin <code>{admin_id}</code> qoʻshildi!</b>", parse_mode='HTML')
    except:
        bot.send_message(message.chat.id, "<b>❌ Notoʻgʻri ID!</b>", parse_mode='HTML')

def remove_admin_id(message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        admin_id = int(message.text.strip())
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

# Kanal qo'shish/o'chirish (majburiy obuna uchun)
def add_channel_username(message):
    if not is_admin(message.from_user.id):
        return
    
    channel = message.text.strip()
    if not channel.startswith('@'):
        bot.send_message(message.chat.id, "<b>❌ Kanal @ bilan boshlanishi kerak!</b>", parse_mode='HTML')
        return
    
    # Tekshirish: bot kanalga kirganmi? (maxfiy ham)
    try:
        bot.get_chat_member(channel, bot.get_me().id)
        # Muvaffaqiyatli bo'lsa, qo'shish
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO channels (channel_id) VALUES (?)', (channel,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"<b>✅ Kanal <code>{channel}</code> qoʻshildi! (Majburiy obuna uchun. Bot kanal admini ekanligi tekshirildi)</b>", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"<b>❌ Xato: Bot {channel} kanaliga kira olmayapti yoki admin emas. {e}</b>", parse_mode='HTML')

def remove_channel_username(message):
    if not is_admin(message.from_user.id):
        return
    
    channel = message.text.strip()
    if not channel.startswith('@'):
        bot.send_message(message.chat.id, "<b>❌ Kanal @ bilan boshlanishi kerak!</b>", parse_mode='HTML')
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    if deleted:
        bot.send_message(message.chat.id, f"<b>✅ Kanal <code>{channel}</code> oʻchirildi! (Majburiy obuna roʻyxatidan olib tashlandi)</b>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Kanal topilmadi!</b>", parse_mode='HTML')

# Kanallar ro'yxati (majburiy obuna uchun)
def get_channels_list():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id FROM channels')
    channels = cursor.fetchall()
    conn.close()
    if channels:
        list_text = "<b>📢 Majburiy obuna kanallari:</b>\n\n" + "\n".join([f"• <code>{c[0]}</code>" for c in channels])
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

# Ulashish linki
def generate_share_link(message):
    if not is_admin(message.from_user.id):
        return
    
    code = message.text.strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM animes WHERE code = ?', (code,))
    anime = cursor.fetchone()
    conn.close()
    
    if anime:
        bot_username = bot.get_me().username
        share_url = f"https://t.me/{bot_username}?start={code}"
        bot.send_message(message.chat.id, f"<b>🔗 Ulashish uchun link:</b>\n<code>{share_url}</code>\n\n<i>Bu link bosilganda avto start boʻladi va fasllar chiqadi.</i>", parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, "<b>❌ Kod topilmadi!</b>", parse_mode='HTML')

# Botni ishga tushirish
if __name__ == '__main__':
    print("🤖 Bot ishga tushdi...")
    bot.polling(none_stop=True)