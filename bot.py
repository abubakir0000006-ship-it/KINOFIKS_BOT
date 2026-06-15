import asyncio
import sqlite3
import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

logging.basicConfig(level=logging.INFO)

# ========== ТВОИ ДАННЫЕ ==========
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
CHANNEL_URL = "https://t.me/+PpgAdF1iQ8xhODEy"
ADMINS = [8925518277, 8350819510]
# =================================

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()

# ========== СТАРЫЕ ТАБЛИЦЫ ==========
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_history (
    user_id INTEGER,
    film_code TEXT,
    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(film_code) REFERENCES movies(code)
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER,
    film_code TEXT,
    PRIMARY KEY (user_id, film_code)
)''')

# ========== НОВЫЕ ТАБЛИЦЫ ДЛЯ СЕРИАЛОВ ==========
cursor.execute('''CREATE TABLE IF NOT EXISTS series (
    code TEXT,
    series_number INTEGER,
    file_id TEXT,
    description TEXT,
    PRIMARY KEY (code, series_number)
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS series_progress (
    user_id INTEGER,
    series_code TEXT,
    last_series INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, series_code)
)''')

# ========== ДОБАВЛЯЕМ КОЛОНКУ is_series В movies (миграция) ==========
try:
    cursor.execute('ALTER TABLE movies ADD COLUMN is_series INTEGER DEFAULT 0')
except sqlite3.OperationalError:
    pass  # колонка уже существует

conn.commit()

# ========== СОСТОЯНИЯ (старые) ==========
class AddMovie(StatesGroup):
    file_id = State()
    code = State()
    description = State()

class Mailing(StatesGroup):
    text = State()

class DelMovie(StatesGroup):
    code = State()

# ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ СЕРИАЛОВ ==========
class AddSeries(StatesGroup):
    code = State()
    series_num = State()
    file_id = State()
    description = State()
    another = State()

# ========== КЛАВИАТУРЫ (добавлены кнопки для сериалов) ==========
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="🎬 Serial qo'shish"), KeyboardButton(text="🗑 Serial o'chirish")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📊 Detallar")],
    [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🔥 Tasodifiy kino")],
    [KeyboardButton(text="⭐️ TOP 10"), KeyboardButton(text="📜 Tarix")],
    [KeyboardButton(text="❤️ Izlanganlar"), KeyboardButton(text="👤 Profil")],
    [KeyboardButton(text="❌ Bekor qilish")]
], resize_keyboard=True)

user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐️ TOP 10")],
    [KeyboardButton(text="📜 Tarix"), KeyboardButton(text="❤️ Izlanganlar")],
    [KeyboardButton(text="👤 Profil"), KeyboardButton(text="❌ Bekor qilish")]
], resize_keyboard=True)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# ========== СТАРЫЕ ХЕНДЛЕРЫ (НЕ ТРОГАЛИ, КРОМЕ НЕБОЛЬШИХ ПРАВОК В RANDOM/TOP) ==========
@dp.message(Command("start"))
async def start(message: types.Message):
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (message.from_user.id,))
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
        await call.message.edit_text("✅ Rahmat! Kino kodini yuboring.", reply_markup=user_kb)
    else:
        await call.answer("❌ Obuna bo'lmadingiz! Kanalga kiring.", show_alert=True)

@dp.callback_query(F.data.startswith("like_"))
async def handle_like(call: types.CallbackQuery):
    code = call.data.split("_")[1]
    action = call.data.split("_")[2]
    if action == "up":
        cursor.execute('UPDATE movies SET likes = likes + 1 WHERE code = ?', (code,))
    else:
        cursor.execute('UPDATE movies SET dislikes = dislikes + 1 WHERE code = ?', (code,))
    conn.commit()
    await call.answer("✅ Ovoz berdingiz!")

@dp.callback_query(F.data.startswith("report_"))
async def handle_report(call: types.CallbackQuery):
    code = call.data.split("_")[1]
    for admin in ADMINS:
        try:
            await bot.send_message(admin, f"⚠️ Shikoyat: Kino kodi {code} (User: {call.from_user.id})")
        except:
            pass
    await call.answer("✅ Shikoyat yuborildi!")

@dp.message(F.text == "👤 Profil")
async def profile(message: types.Message):
    cursor.execute('SELECT viewed_count FROM users WHERE user_id = ?', (message.from_user.id,))
    res = cursor.fetchone()
    count = res[0] if res else 0
    await message.answer(f"👤 Sizning profilingiz\n🎬 Ko'rilgan kinolar soni: {count}")

@dp.message(F.text == "⭐️ TOP 10")
async def top_movies(message: types.Message):
    # показываем только обычные фильмы (is_series = 0)
    cursor.execute('SELECT code, likes FROM movies WHERE is_series = 0 ORDER BY likes DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = "⭐️ TOP 10 eng yaxshi kinolar:\n\n"
    for i, m in enumerate(movies, 1):
        text += f"{i}. 🎬 Kod: {m[0]} | 👍 {m[1]}\n"
    await message.answer(text)

@dp.message(F.text == "📊 Statistika")
async def stats(message: types.Message):
    if message.from_user.id not in ADMINS: return
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    await message.answer(f"👥 Foydalanuvchilar: {count}")

@dp.message(F.text == "📢 Xabar yuborish")
async def mailing_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    await message.answer("📝 Xabarni yozing:")
    await state.set_state(Mailing.text)

@dp.message(Mailing.text)
async def mailing_process(message: types.Message, state: FSMContext):
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    for user in users:
        try:
            await bot.send_message(user[0], message.text)
        except:
            continue
    await message.answer("✅ Yuborildi!", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "➕ K
