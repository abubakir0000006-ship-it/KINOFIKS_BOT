import asyncio
import sqlite3
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

logging.basicConfig(level=logging.INFO)

# Твои данные
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
CHANNEL_URL = "https://t.me/A_ToolsX" # Исправил на ссылку из твоего скрина
ADMINS = [8925518277, 8350819510]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# База данных
conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS serials (code TEXT PRIMARY KEY, title TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS episodes (code TEXT, ep_num INTEGER, file_id TEXT)')
conn.commit()

# Состояния
class AddMovie(StatesGroup):
    file_id = State(); code = State(); description = State()
class Mailing(StatesGroup):
    text = State()
class DelMovie(StatesGroup):
    code = State()

# Кнопки
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="👤 Profil")]
], resize_keyboard=True)

user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="👤 Profil")]
], resize_keyboard=True)

async def is_subscribed(user_id):
    if user_id in ADMINS: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

@dp.message(Command("start"))
async def start(message: types.Message):
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (message.from_user.id,))
    conn.commit()
    if message.from_user.id in ADMINS:
        await message.answer("👑 Admin panel:", reply_markup=admin_kb)
    else:
        await message.answer("🎬 Kino yoki serial kodini yuboring:", reply_markup=user_kb)

# Главный обработчик (сначала проверка подписки, потом всё остальное)
@dp.message(F.text)
async def main_handler(message: types.Message):
    # Если это админские кнопки
    if message.from_user.id in ADMINS:
        if message.text == "➕ Kino qo'shish": return # FSM обработает
        if message.text == "📊 Statistika": 
            cursor.execute('SELECT COUNT(*) FROM users'); count = cursor.fetchone()[0]
            return await message.answer(f"👥 Foydalanuvchilar: {count}")

    # Проверка подписки для всех
    if not await is_subscribed(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")]
        ])
        return await message.answer("⚠️ Kino ko'rish uchun kanalga obuna bo'ling!", reply_markup=kb)

    # Логика поиска
    text = message.text
    # Поиск кино
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies WHERE code = ?', (text,))
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍 {res[3]}", callback_data=f"like_{res[0]}_up"), InlineKeyboardButton(text=f"👎 {res[4]}", callback_data=f"like_{res[0]}_down")],
            [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{res[0]}")]
        ])
        return await bot.send_video(message.chat.id, res[1], caption=f"{res[2]}\n\n🎬 Kod: {res[0]}", reply_markup=kb)

    # Поиск сериала
    cursor.execute('SELECT title FROM serials WHERE code = ?', (text,))
    ser = cursor.fetchone()
    if ser:
        cursor.execute('SELECT ep_num FROM episodes WHERE code = ?', (text,))
        eps = cursor.fetchall()
        kb_ep = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Qism {e[0]}", callback_data=f"ep_{text}_{e[0]}")] for e in eps])
        return await message.answer(f"🎬 Serial: {ser[0]}\nTanlang:", reply_markup=kb_ep)

    if text not in ["👤 Profil", "⭐ TOP 10", "🔥 Tasodifiy kino"]:
        await message.answer("❌ Topilmadi.")

# Колбэки
@dp.callback_query(F.data == "check_sub")
async def check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id): await call.message.answer("✅ Rahmat! Endi kod yuboring.", reply_markup=user_kb)
    else: await call.answer("❌ Hali obuna bo'lmadingiz!", show_alert=True)

@dp.callback_query(F.data.startswith("like_"))
async def handle_like(call: types.CallbackQuery):
    _, code, action = call.data.split("_")
    cursor.execute(f'UPDATE movies SET {"likes" if action=="up" else "dislikes"} = {"likes" if action=="up" else "dislikes"} + 1 WHERE code = ?', (code,))
    conn.commit(); await call.answer("✅ Ovoz berildi!")

@dp.callback_query(F.data.startswith("ep_"))
async def get_ep(call: types.CallbackQuery):
    _, code, ep = call.data.split("_")
    cursor.execute('SELECT file_id FROM episodes WHERE code = ? AND ep_num = ?', (code, ep))
    res = cursor.fetchone()
    if res: await bot.send_video(call.message.chat.id, res[0], caption=f"🎬 Qism: {ep}")

# Профиль и ТОП
@dp.message(F.text == "👤 Profil")
async def profile(message: types.Message):
    cursor.execute('SELECT viewed_count FROM users WHERE user_id = ?', (message.from_user.id,))
    res = cursor.fetchone()
    await message.answer(f"👤 Ko'rilgan kinolar soni: {res[0] if res else 0}")

@dp.message(F.text == "⭐ TOP 10")
async def top_movies(message: types.Message):
    cursor.execute('SELECT code, likes FROM movies ORDER BY likes DESC LIMIT 10')
    movies = cursor.fetchall()
    text = "⭐ TOP 10:\n" + "\n".join([f"🎬 {m[0]} | 👍 {m[1]}" for m in movies])
    await message.answer(text if movies else "❌ Hali kinolar yo'q.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
