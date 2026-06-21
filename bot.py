import asyncio
import sqlite3
import os
import logging
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
 
logging.basicConfig(level=logging.INFO)
 
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
CHANNEL_URL = "https://t.me/+PpgAdF1iQ8xhODEy"
ADMINS = [8925518277, 8350819510]
 
# НОВОЕ: архивный канал для хранения видео навечно (бот должен быть админом в этом канале)
ARCHIVE_CHANNEL_ID = -1003788948077
 
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
 
# НОВОЕ: используем постоянный диск Render (Persistent Disk), если он подключён.
# На Render временная папка проекта (/opt/render/project/src) стирается при
# каждом деплое — поэтому база там не выживает между обновлениями.
# Если в настройках Render подключён диск с Mount Path = /var/data,
# бот будет хранить там movies.db, и база переживёт любой деплой.
# Если диск пока не подключён — работает как раньше, локально (без сюрпризов).
PERSISTENT_DIR = "/var/data"
if os.path.isdir(PERSISTENT_DIR):
    DB_PATH = os.path.join(PERSISTENT_DIR, "movies.db")
else:
    DB_PATH = "movies.db"
 
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
 
# ============================================================
# СТАРЫЕ ТАБЛИЦЫ (не трогаем)
# ============================================================
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code))')
cursor.execute('CREATE TABLE IF NOT EXISTS series (series_code TEXT, episode_num INTEGER, file_id TEXT, description TEXT, PRIMARY KEY(series_code, episode_num))')
conn.commit()
 
# ============================================================
# НОВЫЕ ТАБЛИЦЫ
# ============================================================
try:
    cursor.execute('ALTER TABLE movies ADD COLUMN genre TEXT DEFAULT "other"')
    conn.commit()
except: pass
try:
    cursor.execute('ALTER TABLE movies ADD COLUMN view_count INTEGER DEFAULT 0')
    conn.commit()
except: pass
try:
    cursor.execute('ALTER TABLE users ADD COLUMN username TEXT')
    conn.commit()
except: pass
try:
    cursor.execute('ALTER TABLE users ADD COLUMN notify_series INTEGER DEFAULT 1')
    conn.commit()
except: pass
 
cursor.execute('''CREATE TABLE IF NOT EXISTS history (
    user_id INTEGER,
    code TEXT,
    watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, code)
)''')
 
cursor.execute('''CREATE TABLE IF NOT EXISTS series_subscribers (
    user_id INTEGER,
    series_code TEXT,
    PRIMARY KEY(user_id, series_code)
)''')
conn.commit()
 
# НОВОЕ: подборки от редакции ("Топ недели" и т.п.)
cursor.execute('''CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    codes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
conn.commit()
 
# ============================================================
# СТАРЫЕ СОСТОЯНИЯ (не трогаем)
# ============================================================
class AddMovie(StatesGroup):
    file_id = State()
    code = State()
    description = State()
 
class Mailing(StatesGroup):
    text = State()
    photo = State()
 
class DelMovie(StatesGroup):
    code = State()
 
class AddSeries(StatesGroup):
    series_code = State()
    description = State()
    episode_video = State()
 
# ============================================================
# НОВЫЕ СОСТОЯНИЯ
# ============================================================
class AddMovieNew(StatesGroup):
    file_id = State()
    code = State()
    description = State()
    genre = State()
 
class SearchMovie(StatesGroup):
    query = State()
 
class CreateCollection(StatesGroup):
    title = State()
    codes = State()
 
class Quiz(StatesGroup):
    mood = State()
    time = State()
 
# ============================================================
# КЛАВИАТУРЫ (старые + новые кнопки)
# ============================================================
GENRES = {
    "action": "💥 Jangari",
    "comedy": "😂 Komediya",
    "drama": "🎭 Drama",
    "horror": "👻 Qo'rqinchli",
    "love": "❤️ Sevgi",
    "thriller": "🔪 Triller",
    "fantasy": "🪄 Fantastika",
    "cartoon": "🎠 Multfilm",
    "series": "📺 Serial",
    "other": "🎬 Boshqa"
}
 
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="📺 Serial qo'shish"), KeyboardButton(text="📋 Barcha kinolar")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🔍 Qidirish")],
    # НОВОЕ
    [KeyboardButton(text="🗂 Tanlov yaratish"), KeyboardButton(text="🎯 Nima ko'raman?")],
    [KeyboardButton(text="💾 Bazani yuklab olish")]
], resize_keyboard=True)
 
user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="🎭 Janrlar"), KeyboardButton(text="🔍 Qidirish")],
    [KeyboardButton(text="📜 Tarix"), KeyboardButton(text="👤 Profil")],
    # НОВОЕ
    [KeyboardButton(text="🗂 Tanlovlar"), KeyboardButton(text="🎯 Nima ko'raman?")]
], resize_keyboard=True)
 
# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (старые — не трогаем)
# ============================================================
async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False
 
def is_favorite(user_id, code):
    cursor.execute('SELECT 1 FROM favorites WHERE user_id = ? AND code = ?', (user_id, code))
    return cursor.fetchone() is not None
 
def build_movie_kb(user_id, code, likes, dislikes):
    fav = is_favorite(user_id, code)
    fav_text = "💔 O'chirish" if fav else "❤️ Saqlash"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"like|{code}|up"),
         InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"like|{code}|down")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav|{code}")],
        [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report|{code}"),
         InlineKeyboardButton(text="📺 Shunga o'xshash", callback_data=f"similar|{code}")]
    ])
 
def build_series_kb(series_code, ep_num, total_eps, user_id):
    fav_code = f"series:{series_code}:{ep_num}"
    fav = is_favorite(user_id, fav_code)
    fav_text = "💔 O'chirish" if fav else "❤️ Saqlash"
    nav_row = []
    if ep_num > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"ep|{series_code}|{ep_num - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{ep_num}/{total_eps}", callback_data="noop"))
    if ep_num < total_eps:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"ep|{series_code}|{ep_num + 1}"))
 
    # Проверяем подписан ли на уведомления
    cursor.execute('SELECT 1 FROM series_subscribers WHERE user_id=? AND series_code=?', (user_id, series_code))
    subbed = cursor.fetchone()
    notif_text = "🔕 Bildirishnomani o'chirish" if subbed else "🔔 Yangi qism chiqsa xabar ber"
 
    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text=fav_text, callback_data=f"favseries|{series_code}|{ep_num}")],
        [InlineKeyboardButton(text=notif_text, callback_data=f"notif_series|{series_code}")]
    ])
 
def add_to_history(user_id, code):
    try:
        cursor.execute('INSERT OR REPLACE INTO history (user_id, code, watched_at) VALUES (?, ?, ?)',
                      (user_id, code, datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit()
    except: pass
 
def genres_display(genre_field, emoji_only=False):
    """НОВОЕ: жанры теперь хранятся через запятую — эта функция красиво их отображает.
    emoji_only=True вернёт только первый emoji (для коротких списков в одну строку)."""
    if not genre_field:
        return "🎬" if emoji_only else "🎬 Boshqa"
    parts = [g for g in genre_field.split(",") if g]
    if not parts:
        return "🎬" if emoji_only else "🎬 Boshqa"
    if emoji_only:
        return GENRES.get(parts[0], "🎬").split(" ")[0]
    return ", ".join([GENRES.get(p, p) for p in parts])
 
# НОВОЕ: пересылаем видео в архивный канал и возвращаем "вечный" file_id оттуда.
# Это решает проблему "бот хранит фильм недолго, потом видео пропадает" —
# file_id привязанный к посту в канале не протухает, в отличие от file_id
# полученного просто в личке с ботом.
async def archive_video(file_id, caption=""):
    try:
        sent = await bot.send_video(ARCHIVE_CHANNEL_ID, file_id, caption=caption)
        return sent.video.file_id
    except Exception as e:
        logging.error(f"Arxivga yuklashda xatolik: {e}")
        return file_id  # если не получилось — используем оригинальный, чтобы не ломать процесс
 
# ============================================================
# НОВОЕ: ЗАЩИТА БАЗЫ ДАННЫХ ОТ ПОТЕРИ ПРИ ОБНОВЛЕНИЯХ/ДЕПЛОЯХ
# ============================================================
# Идея: если хостинг стирает диск при каждом обновлении кода — файл movies.db
# теряется, и весь список фильмов "пропадает", даже если сами видео живы
# в архивном канале. Чтобы это исправить, бот сам хранит резервную копию
# базы данных в архивном канале (как обычный документ) и при старте
# проверяет: если локальная база "пустая" — автоматически скачивает
# последний бэкап и восстанавливает её.
 
BACKUP_MARKER = "#MOVIES_DB_BACKUP"  # по этой подписи бот находит свои бэкапы в канале
 
async def backup_db_to_channel():
    """НОВОЕ: отправляет текущий файл базы данных в архивный канал как документ
    и ЗАКРЕПЛЯЕТ это сообщение. Закреп хранится в самом Telegram, а не на
    диске сервера — поэтому он переживёт любой сброс диска при обновлении.
    При следующем запуске бот просто смотрит на закреплённое сообщение
    канала и сразу знает, где лежит последний бэкап."""
    try:
        conn.commit()
        sent = await bot.send_document(
            ARCHIVE_CHANNEL_ID,
            FSInputFile(DB_PATH),
            caption=f"{BACKUP_MARKER}\n💾 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        await bot.pin_chat_message(ARCHIVE_CHANNEL_ID, sent.message_id, disable_notification=True)
    except Exception as e:
        logging.error(f"Bazani arxivga zaxiralashda xatolik: {e}")
 
def db_is_empty():
    """Проверяет, есть ли вообще фильмы/серии в базе (чтобы понять — это 'чистый' старт после потери диска или нет)."""
    try:
        cursor.execute('SELECT COUNT(*) FROM movies')
        movies_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM series')
        series_count = cursor.fetchone()[0]
        return (movies_count + series_count) == 0
    except Exception:
        return True
 
async def restore_db_from_channel_if_needed():
    """НОВОЕ: при запуске бота — если локальная база пустая, бот смотрит на
    ЗАКРЕПЛЁННОЕ сообщение в архивном канале (там лежит последний бэкап
    movies.db) и автоматически восстанавливает базу из него.
 
    Это надёжнее перебора истории канала, потому что закреп — это указатель,
    который хранится на стороне Telegram и не зависит от диска сервера."""
    global conn, cursor
    if not db_is_empty():
        logging.info("Baza bo'sh emas, tiklash kerak emas.")
        return
    try:
        logging.info("Baza bo'sh — arxiv kanalining qadalgan xabaridan zaxira nusxa qidirilmoqda...")
        chat = await bot.get_chat(ARCHIVE_CHANNEL_ID)
        pinned = chat.pinned_message
        if not pinned or not pinned.document:
            logging.warning("Qadalgan zaxira xabari topilmadi. Admin /restore_db buyrug'ini sinab ko'rishi mumkin.")
            return
        if pinned.caption and BACKUP_MARKER in pinned.caption:
            file = await bot.get_file(pinned.document.file_id)
            await bot.download_file(file.file_path, destination=DB_PATH)
            conn.close()
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            cursor = conn.cursor()
            logging.info("✅ Baza arxivdan muvaffaqiyatli tiklandi!")
            for admin_id in ADMINS:
                try:
                    await bot.send_message(admin_id, "✅ Bot qayta ishga tushdi va bazani arxivdan avtomatik tikladi!")
                except: pass
        else:
            logging.warning("Qadalgan xabar zaxira nusxasi emas.")
    except Exception as e:
        logging.error(f"Tiklashga urinishda xatolik: {e}")
 
 
# ============================================================
# СТАРЫЕ ХЕНДЛЕРЫ (не трогаем)
# ============================================================
@dp.message(Command("start"))
async def start(message: types.Message):
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (message.from_user.id,))
    # Сохраняем username
    if message.from_user.username:
        cursor.execute('UPDATE users SET username=? WHERE user_id=?',
                      (message.from_user.username, message.from_user.id))
    conn.commit()
    if message.from_user.id in ADMINS:
        await message.answer("👑 Admin panel:", reply_markup=admin_kb)
    elif not await is_subscribed(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Obuna bo'lish", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")]
        ])
        await message.answer("👋 Kino ko'rish uchun kanalga obuna bo'ling!", reply_markup=kb)
    else:
        await message.answer("🎬 Kino kodini yuboring:", reply_markup=user_kb)
 
@dp.callback_query(F.data == "check_sub")
async def check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.edit_text("✅ Rahmat! Kino kodini yuboring.")
        await bot.send_message(call.from_user.id, "🎬 Menyudan foydalaning:", reply_markup=user_kb)
    else:
        await call.answer("❌ Obuna bo'lmadingiz! Kanalga kiring.", show_alert=True)
 
@dp.callback_query(F.data == "noop")
async def noop(call: types.CallbackQuery):
    await call.answer()
 
@dp.callback_query(F.data.startswith("like|"))
async def handle_like(call: types.CallbackQuery):
    _, code, action = call.data.split("|")
    if action == "up":
        cursor.execute('UPDATE movies SET likes = likes + 1 WHERE code = ?', (code,))
    else:
        cursor.execute('UPDATE movies SET dislikes = dislikes + 1 WHERE code = ?', (code,))
    conn.commit()
    await call.answer("✅ Ovoz berdingiz!")
 
@dp.callback_query(F.data.startswith("report|"))
async def handle_report(call: types.CallbackQuery):
    _, code = call.data.split("|")
    for admin in ADMINS:
        try:
            await bot.send_message(admin, f"⚠️ Shikoyat: Kino kodi {code} (User: {call.from_user.id})")
        except: pass
    await call.answer("✅ Shikoyat yuborildi!")
 
@dp.callback_query(F.data.startswith("fav|"))
async def handle_fav(call: types.CallbackQuery):
    _, code = call.data.split("|")
    user_id = call.from_user.id
    if is_favorite(user_id, code):
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND code = ?', (user_id, code))
        conn.commit()
        await call.answer("💔 O'chirildi")
    else:
        cursor.execute('INSERT OR IGNORE INTO favorites (user_id, code) VALUES (?, ?)', (user_id, code))
        conn.commit()
        await call.answer("❤️ Saqlandi")
    cursor.execute('SELECT likes, dislikes FROM movies WHERE code = ?', (code,))
    res = cursor.fetchone()
    if res:
        try:
            await call.message.edit_reply_markup(reply_markup=build_movie_kb(user_id, code, res[0], res[1]))
        except: pass
 
@dp.callback_query(F.data.startswith("favseries|"))
async def handle_fav_series(call: types.CallbackQuery):
    _, series_code, ep_num = call.data.split("|")
    user_id = call.from_user.id
    fav_code = f"series:{series_code}:{ep_num}"
    if is_favorite(user_id, fav_code):
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND code = ?', (user_id, fav_code))
        conn.commit()
        await call.answer("💔 O'chirildi")
    else:
        cursor.execute('INSERT OR IGNORE INTO favorites (user_id, code) VALUES (?, ?)', (user_id, fav_code))
        conn.commit()
        await call.answer("❤️ Saqlandi")
    cursor.execute('SELECT COUNT(*) FROM series WHERE series_code = ?', (series_code,))
    total_eps = cursor.fetchone()[0]
    try:
        await call.message.edit_reply_markup(
            reply_markup=build_series_kb(series_code, int(ep_num), total_eps, user_id))
    except: pass
 
@dp.callback_query(F.data.startswith("ep|"))
async def handle_episode_nav(call: types.CallbackQuery):
    _, series_code, ep_num = call.data.split("|")
    ep_num = int(ep_num)
    user_id = call.from_user.id
    cursor.execute('SELECT file_id, description FROM series WHERE series_code = ? AND episode_num = ?',
                  (series_code, ep_num))
    res = cursor.fetchone()
    if not res:
        await call.answer("❌ Topilmadi.", show_alert=True)
        return
    cursor.execute('SELECT COUNT(*) FROM series WHERE series_code = ?', (series_code,))
    total_eps = cursor.fetchone()[0]
    file_id, description = res
    kb = build_series_kb(series_code, ep_num, total_eps, user_id)
    try:
        await call.message.delete()
    except: pass
    await bot.send_video(call.message.chat.id, file_id,
                         caption=f"{description}\n\n🎬 Serial: {series_code} | {ep_num}-qism",
                         reply_markup=kb)
    add_to_history(user_id, f"series:{series_code}:{ep_num}")
    await call.answer()
 
@dp.message(F.text == "👤 Profil")
async def profile(message: types.Message):
    cursor.execute('SELECT viewed_count FROM users WHERE user_id = ?', (message.from_user.id,))
    res = cursor.fetchone()
    count = res[0] if res else 0
    cursor.execute('SELECT COUNT(*) FROM favorites WHERE user_id=?', (message.from_user.id,))
    fav_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM history WHERE user_id=?', (message.from_user.id,))
    hist_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM series_subscribers WHERE user_id=?', (message.from_user.id,))
    sub_count = cursor.fetchone()[0]
    username = f"@{message.from_user.username}" if message.from_user.username else "Yo'q"
    await message.answer(
        f"👤 Sizning profilingiz\n\n"
        f"🆔 ID: {message.from_user.id}\n"
        f"📛 Username: {username}\n"
        f"🎬 Ko'rilgan kinolar: {count}\n"
        f"📜 Tarix: {hist_count} ta\n"
        f"❤️ Saqlanganlar: {fav_count} ta\n"
        f"🔔 Kuzatilayotgan seriallar: {sub_count} ta"
    )
 
@dp.message(F.text == "⭐ TOP 10")
async def top_movies(message: types.Message):
    cursor.execute('SELECT code, likes, view_count FROM movies ORDER BY likes DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = "⭐ TOP 10 eng yaxshi kinolar:\n\n"
    for i, m in enumerate(movies, 1):
        text += f"{i}. 🎬 Kod: {m[0]} | 👍 {m[1]} | 👁 {m[2]}\n"
    await message.answer(text)
 
@dp.message(F.text == "🆕 Yangi kinolar")
async def new_movies(message: types.Message):
    cursor.execute('SELECT code, description, genre FROM movies ORDER BY added_at DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = "🆕 Yangi qo'shilgan kinolar:\n\n"
    for m in movies:
        desc = (m[1][:40] + "...") if len(m[1]) > 40 else m[1]
        genre_emoji = genres_display(m[2], emoji_only=True)
        text += f"{genre_emoji} Kod: {m[0]} — {desc}\n"
    text += "\nKino kodini yuborib ko'ring!"
    await message.answer(text)
 
@dp.message(F.text == "📁 Saqlanganlar")
async def favorites_list(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('SELECT code FROM favorites WHERE user_id = ?', (user_id,))
    favs = cursor.fetchall()
    if not favs:
        await message.answer("❌ Sizda hali saqlangan kinolar yo'q.")
        return
    text = "📁 Sizning saqlanganlaringiz:\n\n"
    for f in favs:
        code = f[0]
        if code.startswith("series:"):
            _, series_code, ep_num = code.split(":")
            text += f"📺 {series_code} — {ep_num}-qism\n"
        else:
            text += f"🎬 Kod: {code}\n"
    await message.answer(text)
 
@dp.message(F.text == "📊 Statistika")
async def stats(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM movies')
    movie_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(DISTINCT series_code) FROM series')
    series_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM favorites')
    fav_count = cursor.fetchone()[0]
    cursor.execute('SELECT code, view_count FROM movies ORDER BY view_count DESC LIMIT 3')
    top = cursor.fetchall()
    top_text = "\n".join([f"  {i+1}. {t[0]} — {t[1]} marta" for i, t in enumerate(top)]) or "  Yo'q"
    await message.answer(
        f"📊 Bot statistikasi:\n\n"
        f"👥 Foydalanuvchilar: {user_count}\n"
        f"🎬 Kinolar: {movie_count}\n"
        f"📺 Seriallar: {series_count}\n"
        f"❤️ Jami saqlanganlar: {fav_count}\n\n"
        f"🔥 Eng ko'p ko'rilgan:\n{top_text}"
    )
 
@dp.message(F.text == "📢 Xabar yuborish")
async def mailing_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📸 Rasm yuboring yoki /skip yozing (rasmsiz yuborish uchun):")
    await state.set_state(Mailing.photo)
 
@dp.message(Mailing.photo, F.photo)
async def mailing_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("📝 Xabar matnini yozing:")
    await state.set_state(Mailing.text)
 
@dp.message(Mailing.photo, Command("skip"))
async def mailing_skip_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=None)
    await message.answer("📝 Xabar matnini yozing:")
    await state.set_state(Mailing.text)
 
@dp.message(Mailing.text, ~F.text.startswith("/"))
async def mailing_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo = data.get('photo')
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    sent = 0
    for user in users:
        try:
            if photo:
                await bot.send_photo(user[0], photo, caption=message.text)
            else:
                await bot.send_message(user[0], message.text)
            sent += 1
        except: continue
    await message.answer(f"✅ Yuborildi! {sent} ta foydalanuvchiga yetdi.", reply_markup=admin_kb)
    await state.clear()
 
@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📹 Videoni yuboring (rus tilida/asosiy versiya):")
    await state.set_state(AddMovieNew.file_id)
 
@dp.message(AddMovieNew.file_id, F.video | F.document)
async def get_video_new(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    await state.update_data(file_id=file_id)
    await message.answer("🔢 Kodini yozing:")
    await state.set_state(AddMovieNew.code)
 
@dp.message(AddMovieNew.code, ~F.text.startswith("/"))
async def get_code_new(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text)
    await message.answer("📝 Kinosining tavsifini yozing:")
    await state.set_state(AddMovieNew.description)
 
def build_genre_select_kb(selected_genres):
    """НОВОЕ: клавиатура мультивыбора жанров — отмеченные жанры показываются с галочкой ✅"""
    rows = []
    for k, v in GENRES.items():
        text = f"✅ {v}" if k in selected_genres else v
        rows.append([InlineKeyboardButton(text=text, callback_data=f"togglegenre|{k}")])
    rows.append([InlineKeyboardButton(text="✔️ Tayyor", callback_data="genredone")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
 
@dp.message(AddMovieNew.description, ~F.text.startswith("/"))
async def get_description_new(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text, selected_genres=[])
    await message.answer(
        "🎭 Janrlarni tanlang (bir nechtasini tanlash mumkin), so'ng \"✔️ Tayyor\" tugmasini bosing:",
        reply_markup=build_genre_select_kb([])
    )
    await state.set_state(AddMovieNew.genre)
 
@dp.callback_query(F.data.startswith("togglegenre|"), AddMovieNew.genre)
async def toggle_genre(call: types.CallbackQuery, state: FSMContext):
    genre = call.data.split("|")[1]
    data = await state.get_data()
    selected = data.get('selected_genres', [])
    if genre in selected:
        selected.remove(genre)
    else:
        selected.append(genre)
    await state.update_data(selected_genres=selected)
    try:
        await call.message.edit_reply_markup(reply_markup=build_genre_select_kb(selected))
    except: pass
    await call.answer()
 
@dp.callback_query(F.data == "genredone", AddMovieNew.genre)
async def set_genre(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get('selected_genres', [])
    if not selected:
        await call.answer("⚠️ Kamida 1 ta janr tanlang!", show_alert=True)
        return
    # НОВОЕ: храним несколько жанров через запятую, например "love,horror,thriller"
    genre_str = ",".join(selected)
    # НОВОЕ: дублируем видео в архивный канал, чтобы оно хранилось вечно
    archived_file_id = await archive_video(data['file_id'], caption=f"🎬 Kod: {data['code']}")
    cursor.execute(
        'INSERT OR REPLACE INTO movies (code, file_id, description, genre) VALUES (?, ?, ?, ?)',
        (data['code'], archived_file_id, data['description'], genre_str)
    )
    conn.commit()
    genre_names = ", ".join([GENRES.get(g, g) for g in selected])
    await call.message.edit_text(f"✅ Kino saqlandi! Janrlar: {genre_names}")
    await bot.send_message(call.from_user.id, "👑 Admin panel:", reply_markup=admin_kb)
    await state.clear()
    asyncio.create_task(backup_db_to_channel())  # НОВОЕ: бэкапим базу после изменения
 
@dp.message(F.text == "🗑 Kino o'chirish")
async def del_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("❌ O'chirmoqchi bo'lgan kodni yozing:")
    await state.set_state(DelMovie.code)
 
@dp.message(DelMovie.code, ~F.text.startswith("/"))
async def delete_process(message: types.Message, state: FSMContext):
    cursor.execute('DELETE FROM movies WHERE code = ?', (message.text,))
    conn.commit()
    await message.answer("✅ O'chirildi!", reply_markup=admin_kb)
    await state.clear()
    asyncio.create_task(backup_db_to_channel())  # НОВОЕ: бэкапим базу после изменения
 
@dp.message(F.text == "📺 Serial qo'shish")
async def add_series_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🔢 Serial uchun kod kiriting (masalan: BREAKING_BAD):")
    await state.set_state(AddSeries.series_code)
 
@dp.message(AddSeries.series_code, ~F.text.startswith("/"))
async def add_series_code(message: types.Message, state: FSMContext):
    await state.update_data(series_code=message.text.strip(), next_episode=1)
    await message.answer("📝 Serial uchun umumiy tavsif yozing:")
    await state.set_state(AddSeries.description)
 
@dp.message(AddSeries.description, ~F.text.startswith("/"))
async def add_series_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    data = await state.get_data()
    await message.answer(f"📹 1-qism videosini yuboring (Serial: {data['series_code']}):")
    await state.set_state(AddSeries.episode_video)
 
@dp.message(AddSeries.episode_video, F.video | F.document)
async def add_series_episode(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.video.file_id if message.video else message.document.file_id
    ep_num = data['next_episode']
    # НОВОЕ: дублируем серию в архивный канал, чтобы видео хранилось вечно
    archived_file_id = await archive_video(file_id, caption=f"📺 {data['series_code']} | {ep_num}-qism")
    cursor.execute('INSERT OR REPLACE INTO series (series_code, episode_num, file_id, description) VALUES (?, ?, ?, ?)',
                  (data['series_code'], ep_num, archived_file_id, data['description']))
    conn.commit()
    await state.update_data(next_episode=ep_num + 1)
 
    # Уведомляем подписчиков если это не первый эпизод
    if ep_num > 1:
        cursor.execute('SELECT user_id FROM series_subscribers WHERE series_code=?', (data['series_code'],))
        subs = cursor.fetchall()
        for s in subs:
            try:
                await bot.send_message(s[0],
                    f"🔔 Yangi qism chiqdi!\n\n"
                    f"📺 Serial: {data['series_code']}\n"
                    f"▶️ {ep_num}-qism\n\n"
                    f"Kodini yuboring: {data['series_code']}")
            except: pass
 
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Yana qism qo'shish", callback_data="series_more")],
        [InlineKeyboardButton(text="✅ Tugatish", callback_data="series_done")]
    ])
    await message.answer(f"✅ {ep_num}-qism saqlandi! Davom etamizmi?", reply_markup=kb)
    asyncio.create_task(backup_db_to_channel())  # НОВОЕ: бэкапим базу после изменения
 
@dp.callback_query(F.data == "series_more")
async def series_more(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await call.message.edit_text(f"📹 {data['next_episode']}-qism videosini yuboring (Serial: {data['series_code']}):")
    await call.answer()
 
@dp.callback_query(F.data == "series_done")
async def series_done(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    total = data['next_episode'] - 1
    await call.message.edit_text(f"✅ Serial '{data['series_code']}' saqlandi! Jami: {total} qism.")
    await state.clear()
    await bot.send_message(call.from_user.id, "👑 Admin panel:", reply_markup=admin_kb)
    await call.answer()
 
@dp.message(F.text == "🔥 Tasodifiy kino")
async def random_movie(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies ORDER BY RANDOM() LIMIT 1')
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        cursor.execute('UPDATE movies SET view_count = view_count + 1 WHERE code = ?', (res[0],))
        conn.commit()
        add_to_history(message.from_user.id, res[0])
        kb = build_movie_kb(message.from_user.id, res[0], res[3], res[4])
        await bot.send_video(message.chat.id, res[1], caption=f"✨ {res[2]}\n\n🎬 Kod: {res[0]}", reply_markup=kb)
    else:
        await message.answer("❌ Bazada hali kino yo'q.")
 
# ============================================================
# НОВОЕ: 1) РЕЗЕРВНАЯ КОПИЯ БАЗЫ ДЛЯ АДМИНА
# ============================================================
 
@dp.message(F.text == "💾 Bazani yuklab olish")
async def admin_backup(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    try:
        conn.commit()  # на всякий случай сохраняем все изменения перед копией
        await message.answer_document(
            FSInputFile(DB_PATH),
            caption=f"💾 Zaxira nusxa | {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
 
async def daily_auto_backup():
    """НОВОЕ: раз в сутки бот сам отправляет всем админам бэкап базы данных."""
    while True:
        await asyncio.sleep(86400)  # 24 часа
        try:
            conn.commit()
            for admin_id in ADMINS:
                try:
                    await bot.send_document(
                        admin_id,
                        FSInputFile(DB_PATH),
                        caption=f"💾 Avtomatik zaxira nusxa | {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                    )
                except: pass
        except Exception as e:
            logging.error(f"Avto-zaxiralashda xatolik: {e}")
 
# ============================================================
# НОВОЕ: 2) ПОДБОРКИ ОТ РЕДАКЦИИ ("Топ недели" и т.п.)
# ============================================================
@dp.message(F.text == "🗂 Tanlov yaratish")
async def create_collection_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📝 Tanlov nomini yozing (masalan: \"🔥 Hafta TOP-5\"):")
    await state.set_state(CreateCollection.title)
 
@dp.message(CreateCollection.title, ~F.text.startswith("/"))
async def create_collection_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer(
        "🎬 Endi shu tanlovga kiritiladigan kino kodlarini yozing, vergul bilan ajratib.\n\n"
        "Masalan: AB123, CD456, EF789"
    )
    await state.set_state(CreateCollection.codes)
 
@dp.message(CreateCollection.codes, ~F.text.startswith("/"))
async def create_collection_codes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    codes = [c.strip() for c in message.text.split(",") if c.strip()]
    if not codes:
        await message.answer("❌ Hech qanday kod kiritilmadi. Qaytadan urinib ko'ring.")
        return
 
    # Проверяем что коды существуют в базе
    valid_codes = []
    for code in codes:
        cursor.execute('SELECT code FROM movies WHERE code=?', (code,))
        if cursor.fetchone():
            valid_codes.append(code)
 
    if not valid_codes:
        await message.answer("❌ Hech biri topilmadi. Kodlarni tekshirib qaytadan kiriting.")
        return
 
    codes_str = ",".join(valid_codes)
    cursor.execute('INSERT INTO collections (title, codes) VALUES (?, ?)', (data['title'], codes_str))
    conn.commit()
    await message.answer(
        f"✅ Tanlov yaratildi!\n\n🗂 {data['title']}\n🎬 {len(valid_codes)} ta kino qo'shildi.",
        reply_markup=admin_kb
    )
    await state.clear()
 
@dp.message(F.text == "🗂 Tanlovlar")
async def list_collections(message: types.Message):
    cursor.execute('SELECT id, title FROM collections ORDER BY created_at DESC LIMIT 15')
    collections = cursor.fetchall()
    if not collections:
        await message.answer("❌ Hozircha tanlovlar yo'q.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c[1], callback_data=f"showcol|{c[0]}")] for c in collections
    ])
    await message.answer("🗂 Mavjud tanlovlar:", reply_markup=kb)
 
@dp.callback_query(F.data.startswith("showcol|"))
async def show_collection(call: types.CallbackQuery):
    col_id = int(call.data.split("|")[1])
    cursor.execute('SELECT title, codes FROM collections WHERE id=?', (col_id,))
    res = cursor.fetchone()
    if not res:
        await call.answer("❌ Topilmadi", show_alert=True)
        return
    title, codes_str = res
    codes = [c for c in codes_str.split(",") if c]
    text = f"🗂 {title}\n\n"
    for code in codes:
        cursor.execute('SELECT description FROM movies WHERE code=?', (code,))
        m = cursor.fetchone()
        desc = (m[0][:40] + "...") if m and len(m[0]) > 40 else (m[0] if m else "")
        text += f"🎬 Kod: {code} — {desc}\n"
    text += "\nKodini yuboring!"
    await call.message.answer(text)
    await call.answer()
 
# ============================================================
# НОВОЕ: 3) МИНИ-ОПРОС "ЧТО ПОСМОТРЕТЬ?"
# ============================================================
@dp.message(F.text == "🎯 Nima ko'raman?")
async def quiz_start(message: types.Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id) and message.from_user.id not in ADMINS:
        await message.answer("⚠️ Obuna bo'ling!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😂 Kulgili narsa", callback_data="quizmood|comedy")],
        [InlineKeyboardButton(text="😱 Qo'rqinchli narsa", callback_data="quizmood|horror")],
        [InlineKeyboardButton(text="❤️ Romantik narsa", callback_data="quizmood|love")],
        [InlineKeyboardButton(text="💥 Action/qiziqarli", callback_data="quizmood|action")],
        [InlineKeyboardButton(text="🎲 Farqi yo'q, ajablantir", callback_data="quizmood|any")]
    ])
    await message.answer("🎯 Kayfiyatingiz qanday? Nima ko'rishni xohlaysiz?", reply_markup=kb)
 
@dp.callback_query(F.data.startswith("quizmood|"))
async def quiz_mood(call: types.CallbackQuery):
    mood = call.data.split("|")[1]
    if mood == "any":
        cursor.execute('SELECT code, description, file_id, likes, dislikes FROM movies ORDER BY RANDOM() LIMIT 1')
    else:
        cursor.execute(
            "SELECT code, description, file_id, likes, dislikes FROM movies WHERE (',' || genre || ',') LIKE ? ORDER BY RANDOM() LIMIT 1",
            (f'%,{mood},%',)
        )
    res = cursor.fetchone()
    if not res:
        await call.answer("❌ Bu kayfiyat uchun kino topilmadi, boshqasini tanlang!", show_alert=True)
        return
    code, description, file_id, likes, dislikes = res
    user_id = call.from_user.id
    cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('UPDATE movies SET view_count = view_count + 1 WHERE code = ?', (code,))
    conn.commit()
    add_to_history(user_id, code)
    kb = build_movie_kb(user_id, code, likes, dislikes)
    await bot.send_video(call.message.chat.id, file_id,
                         caption=f"🎯 Sizga tavsiya: {description}\n\n🎬 Kod: {code}", reply_markup=kb)
    await call.answer()
 
@dp.message(F.text, ~F.text.startswith("/"))
async def search_movie(message: types.Message, state: FSMContext):
    # Пропускаем кнопки меню
    menu_texts = [
        "🎭 Janrlar", "🔍 Qidirish", "📜 Tarix", "📋 Barcha kinolar",
        # НОВОЕ: новые кнопки тоже должны пропускаться этим хендлером
        "🗂 Tanlov yaratish", "🗂 Tanlovlar", "🎯 Nima ko'raman?", "💾 Bazani yuklab olish"
    ]
    if message.text in menu_texts:
        return
 
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
 
    text = message.text.strip()
 
    # Проверяем сериал
    cursor.execute('SELECT file_id, description FROM series WHERE series_code = ? AND episode_num = 1', (text,))
    series_res = cursor.fetchone()
    if series_res:
        cursor.execute('SELECT COUNT(*) FROM series WHERE series_code = ?', (text,))
        total_eps = cursor.fetchone()[0]
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        file_id, description = series_res
        kb = build_series_kb(text, 1, total_eps, message.from_user.id)
        await bot.send_video(message.chat.id, file_id,
                             caption=f"{description}\n\n🎬 Serial: {text} | 1-qism", reply_markup=kb)
        add_to_history(message.from_user.id, f"series:{text}:1")
        return
 
    # Проверяем фильм
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies WHERE code = ?', (text,))
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        cursor.execute('UPDATE movies SET view_count = view_count + 1 WHERE code = ?', (res[0],))
        conn.commit()
        add_to_history(message.from_user.id, res[0])
        kb = build_movie_kb(message.from_user.id, res[0], res[3], res[4])
        await bot.send_video(message.chat.id, res[1],
                             caption=f"{res[2]}\n\n🎬 Kod: {message.text}", reply_markup=kb)
    else:
        await message.answer("❌ Topilmadi. 🔍 Qidirish tugmasi orqali nom bo'yicha qidiring!")
 
# ============================================================
# НОВЫЕ ХЕНДЛЕРЫ
# ============================================================
 
# --- Список всех фильмов для админа ---
@dp.message(F.text == "📋 Barcha kinolar")
async def all_movies(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    cursor.execute('SELECT code, genre, view_count, likes FROM movies ORDER BY added_at DESC')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = f"📋 Jami {len(movies)} ta kino:\n\n"
    for m in movies:
        genre_emoji = genres_display(m[1], emoji_only=True)
        text += f"{genre_emoji} {m[0]} | 👁{m[2]} | 👍{m[3]}\n"
    await message.answer(text[:4000])
 
# --- НОВОЕ: перезалить старые фильмы/серии в архив (на случай если они были
# добавлены ДО подключения архивного канала и их file_id скоро протухнет) ---
@dp.message(Command("arxivlash"))
async def rearchive_all(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("⏳ Eski kino va seriallarni arxivga ko'chirish boshlandi, biroz kuting...")
 
    cursor.execute('SELECT code, file_id FROM movies')
    movies = cursor.fetchall()
    ok_m, fail_m = 0, 0
    for code, file_id in movies:
        try:
            new_id = await archive_video(file_id, caption=f"🎬 Kod: {code}")
            cursor.execute('UPDATE movies SET file_id=? WHERE code=?', (new_id, code))
            conn.commit()
            ok_m += 1
        except:
            fail_m += 1
 
    cursor.execute('SELECT series_code, episode_num, file_id FROM series')
    episodes = cursor.fetchall()
    ok_s, fail_s = 0, 0
    for series_code, ep_num, file_id in episodes:
        try:
            new_id = await archive_video(file_id, caption=f"📺 {series_code} | {ep_num}-qism")
            cursor.execute('UPDATE series SET file_id=? WHERE series_code=? AND episode_num=?',
                          (new_id, series_code, ep_num))
            conn.commit()
            ok_s += 1
        except:
            fail_s += 1
 
    await message.answer(
        f"✅ Arxivlash tugadi!\n\n"
        f"🎬 Kinolar: {ok_m} muvaffaqiyatli, {fail_m} xato\n"
        f"📺 Seriya qismlari: {ok_s} muvaffaqiyatli, {fail_s} xato\n\n"
        f"Endi bu kino va seriallar hech qachon yo'qolmaydi."
    )
 
# --- НОВОЕ: ручной бэкап базы по команде (на случай если не хочешь ждать автоматический) ---
@dp.message(Command("backup_now"))
async def manual_backup(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("⏳ Baza arxivga zaxiralanmoqda...")
    await backup_db_to_channel()
    await message.answer("✅ Bazaning zaxira nusxasi arxiv kanaliga yuborildi va qadab qo'yildi.")
 
# --- НОВОЕ: диагностика хостинга — помогает понять, временный диск или постоянный ---
@dp.message(Command("server_info"))
async def server_info(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    info_lines = ["🖥 Server haqida ma'lumot:\n"]
 
    # Определяем тип хостинга по характерным переменным окружения
    hosting_hints = []
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
        hosting_hints.append("Railway")
    if os.environ.get("RENDER"):
        hosting_hints.append("Render")
    if os.environ.get("FLY_APP_NAME"):
        hosting_hints.append("Fly.io")
    if os.environ.get("HEROKU_APP_NAME") or os.environ.get("DYNO"):
        hosting_hints.append("Heroku")
 
    if hosting_hints:
        info_lines.append(f"📦 Aniqlangan hosting: {', '.join(hosting_hints)}")
    else:
        info_lines.append("📦 Aniqlangan hosting: noma'lum (ehtimol VPS yoki boshqa xizmat)")
 
    # НОВОЕ: показываем, используется ли постоянный диск
    if os.path.isdir(PERSISTENT_DIR):
        info_lines.append(f"✅ Doimiy disk ulangan: {PERSISTENT_DIR}")
    else:
        info_lines.append(f"⚠️ Doimiy disk topilmadi ({PERSISTENT_DIR} mavjud emas) — baza vaqtinchalik papkada saqlanmoqda!")
    info_lines.append(f"📍 Baza fayli joylashgan joy: {DB_PATH}")
 
    # Проверяем существование и возраст файла базы — намёк, давно ли "живёт" диск
    if os.path.exists(DB_PATH):
        size_kb = os.path.getsize(DB_PATH) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(DB_PATH)).strftime('%d.%m.%Y %H:%M')
        info_lines.append(f"💾 movies.db hajmi: {size_kb:.1f} KB")
        info_lines.append(f"🕐 Oxirgi o'zgartirilgan vaqti: {mtime}")
    else:
        info_lines.append("💾 movies.db topilmadi (!)")
 
    info_lines.append(f"\n📂 Joriy papka: {os.getcwd()}")
    info_lines.append(
        "\nℹ️ Agar bot har safar qayta ishga tushganda (deploy/update) "
        "yuqoridagi 'oxirgi o'zgartirilgan vaqti' joriy vaqtga teng bo'lib qolsa — "
        "demak disk doimiy emas (vaqtinchalik), va bazani saqlash uchun "
        "hosting sozlamalarida 'persistent volume/disk' yoqish kerak."
    )
 
    await message.answer("\n".join(info_lines))
 
# --- НОВОЕ: ручное восстановление базы из архивного канала (на случай если автоматика не сработала) ---
@dp.message(Command("restore_db"))
async def manual_restore(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer(
        "⚠️ DIQQAT! Bu joriy bazani arxivdagi oxirgi zaxira nusxasi bilan almashtiradi.\n"
        "Davom etishni xohlaysizmi?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, tiklash", callback_data="confirm_restore")],
            [InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data="cancel_restore")]
        ])
    )
 
@dp.callback_query(F.data == "confirm_restore")
async def confirm_restore(call: types.CallbackQuery):
    global conn, cursor
    if call.from_user.id not in ADMINS:
        return
    await call.message.edit_text("⏳ Baza arxivdan tiklanmoqda...")
    chat = await bot.get_chat(ARCHIVE_CHANNEL_ID)
    pinned = chat.pinned_message
    if not pinned or not pinned.document or not (pinned.caption and BACKUP_MARKER in pinned.caption):
        await call.message.edit_text("❌ Arxiv kanalida qadalgan zaxira nusxasi topilmadi.")
        return
    try:
        file = await bot.get_file(pinned.document.file_id)
        await bot.download_file(file.file_path, destination=DB_PATH)
        conn.close()
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        await call.message.edit_text("✅ Baza muvaffaqiyatli tiklandi!")
    except Exception as e:
        await call.message.edit_text(f"❌ Xatolik: {e}")
 
@dp.callback_query(F.data == "cancel_restore")
async def cancel_restore(call: types.CallbackQuery):
    await call.message.edit_text("❌ Bekor qilindi.")
 
# --- Жанры ---
@dp.message(F.text == "🎭 Janrlar")
async def genres_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=v, callback_data=f"genre|{k}")] for k, v in GENRES.items()
    ])
    await message.answer("🎭 Janrni tanlang:", reply_markup=kb)
 
@dp.callback_query(F.data.startswith("genre|"))
async def genre_list(call: types.CallbackQuery):
    genre = call.data.split("|")[1]
    # НОВОЕ: жанры хранятся через запятую (например "love,horror"). Чтобы "love" не зацепил
    # случайно похожий жанр, оборачиваем поле и искомое значение запятыми с двух сторон.
    cursor.execute(
        "SELECT code, description FROM movies WHERE (',' || genre || ',') LIKE ? ORDER BY likes DESC LIMIT 10",
        (f'%,{genre},%',)
    )
    movies = cursor.fetchall()
    genre_name = GENRES.get(genre, "🎬")
    if not movies:
        await call.message.answer(f"❌ {genre_name} janrida hali kino yo'q.")
        await call.answer()
        return
    text = f"{genre_name} kinolar:\n\n"
    for m in movies:
        desc = (m[1][:40] + "...") if len(m[1]) > 40 else m[1]
        text += f"🎬 Kod: {m[0]} — {desc}\n"
    text += "\nKodini yuboring!"
    await call.message.answer(text)
    await call.answer()
 
# --- Поиск по названию ---
@dp.message(F.text == "🔍 Qidirish")
async def search_start(message: types.Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
    await message.answer("🔍 Kino nomi yoki tavsifidan so'z kiriting:")
    await state.set_state(SearchMovie.query)
 
@dp.message(SearchMovie.query, ~F.text.startswith("/"))
async def search_process(message: types.Message, state: FSMContext):
    query = message.text.strip()
    cursor.execute(
        'SELECT code, description, genre FROM movies WHERE description LIKE ? OR code LIKE ? LIMIT 10',
        (f'%{query}%', f'%{query}%')
    )
    results = cursor.fetchall()
    await state.clear()
    if not results:
        await message.answer("❌ Hech narsa topilmadi.")
        return
    text = f"🔍 '{query}' bo'yicha natijalar:\n\n"
    for r in results:
        desc = (r[1][:50] + "...") if len(r[1]) > 50 else r[1]
        genre_emoji = genres_display(r[2], emoji_only=True)
        text += f"{genre_emoji} Kod: {r[0]}\n{desc}\n\n"
    text += "Kino kodini yuboring!"
    await message.answer(text)
 
# --- История просмотров ---
@dp.message(F.text == "📜 Tarix")
async def watch_history(message: types.Message):
    cursor.execute(
        'SELECT code, watched_at FROM history WHERE user_id=? ORDER BY watched_at DESC LIMIT 15',
        (message.from_user.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await message.answer("📜 Siz hali hech narsa ko'rmadingiz.")
        return
    text = "📜 Sizning ko'rish tarixingiz:\n\n"
    for r in rows:
        code = r[0]
        date = r[1][:16] if r[1] else ""
        if code.startswith("series:"):
            _, sc, ep = code.split(":")
            text += f"📺 {sc} — {ep}-qism | {date}\n"
        else:
            text += f"🎬 {code} | {date}\n"
    await message.answer(text)
 
# --- Подписка на уведомления о сериале ---
@dp.callback_query(F.data.startswith("notif_series|"))
async def toggle_series_notif(call: types.CallbackQuery):
    _, series_code = call.data.split("|")
    user_id = call.from_user.id
    cursor.execute('SELECT 1 FROM series_subscribers WHERE user_id=? AND series_code=?', (user_id, series_code))
    if cursor.fetchone():
        cursor.execute('DELETE FROM series_subscribers WHERE user_id=? AND series_code=?', (user_id, series_code))
        conn.commit()
        await call.answer("🔕 Bildirishnoma o'chirildi", show_alert=True)
    else:
        cursor.execute('INSERT OR IGNORE INTO series_subscribers (user_id, series_code) VALUES (?, ?)',
                      (user_id, series_code))
        conn.commit()
        await call.answer("🔔 Yangi qism chiqsa xabar beramiz!", show_alert=True)
    # Обновляем клавиатуру
    cursor.execute('SELECT COUNT(*) FROM series WHERE series_code=?', (series_code,))
    total = cursor.fetchone()[0]
    # Получаем текущий номер эпизода из caption
    try:
        caption = call.message.caption or ""
        ep_num = 1
        if "| " in caption:
            part = caption.split("| ")[-1].replace("-qism", "").strip()
            ep_num = int(part)
        await call.message.edit_reply_markup(
            reply_markup=build_series_kb(series_code, ep_num, total, user_id))
    except: pass
 
# --- Похожие фильмы ---
@dp.callback_query(F.data.startswith("similar|"))
async def similar_movies(call: types.CallbackQuery):
    _, code = call.data.split("|")
    cursor.execute('SELECT genre FROM movies WHERE code=?', (code,))
    res = cursor.fetchone()
    if not res or not res[0]:
        await call.answer("❌ Ma'lumot yo'q", show_alert=True)
        return
    movie_genres = [g for g in res[0].split(",") if g]
    if not movie_genres:
        await call.answer("❌ Ma'lumot yo'q", show_alert=True)
        return
    # НОВОЕ: ищем фильмы у которых есть хотя бы ОДИН общий жанр с этим фильмом
    cursor.execute('SELECT code, description, genre FROM movies WHERE code != ?', (code,))
    all_movies = cursor.fetchall()
    similar = []
    for m in all_movies:
        other_genres = [g for g in (m[2] or "").split(",") if g]
        if set(movie_genres) & set(other_genres):
            similar.append(m)
    similar = similar[:5]
    if not similar:
        await call.answer("❌ O'xshash kinolar topilmadi", show_alert=True)
        return
    genre_names = genres_display(res[0])
    text = f"📺 {genre_names} janridagi o'xshash kinolar:\n\n"
    for s in similar:
        desc = (s[1][:40] + "...") if len(s[1]) > 40 else s[1]
        text += f"🎬 Kod: {s[0]} — {desc}\n"
    await call.message.answer(text)
    await call.answer()
 
 
 
# ============================================================
async def run_web():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()
 
async def main():
    await run_web()
    await restore_db_from_channel_if_needed()  # НОВОЕ: автовосстановление базы при "чистом" старте
    asyncio.create_task(daily_auto_backup())  # НОВОЕ: автоматический ежедневный бэкап базы
    await dp.start_polling(bot)
 
if __name__ == "__main__":
    asyncio.run(main())
