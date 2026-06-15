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

# Твои данные
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
CHANNEL_URL = "https://t.me/+PpgAdF1iQ8xhODEy"
ADMINS = [8925518277, 8350819510]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Инициализация БД (фильмы + СЕРИАЛЫ)
conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
# Новые таблицы для сериалов
cursor.execute('CREATE TABLE IF NOT EXISTS serials (code TEXT PRIMARY KEY, title TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS episodes (code TEXT, ep_num INTEGER, file_id TEXT)')
conn.commit()

class AddMovie(StatesGroup):
    file_id = State(); code = State(); description = State()
class Mailing(StatesGroup):
    text = State()
class DelMovie(StatesGroup):
    code = State()

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
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

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
        await call.answer("❌ Obuna bo'lmadingiz!", show_alert=True)

# --- НОВАЯ ЛОГИКА ДЛЯ СЕРИАЛОВ ---
@dp.callback_query(F.data.startswith("ep_"))
async def handle_episode(call: types.CallbackQuery):
    _, code, ep_num = call.data.split("_")
    cursor.execute('SELECT file_id FROM episodes WHERE code = ? AND ep_num = ?', (code, ep_num))
    res = cursor.fetchone()
    if res:
        await bot.send_video(call.message.chat.id, res[0], caption=f"🎬 Serial: {code} | Qism: {ep_num}")
    else:
        await call.answer("❌ Qism topilmadi")
    await call.answer()

# --- СТАРАЯ ЛОГИКА (НЕ ТРОГАЛ) ---
@dp.callback_query(F.data.startswith("like_"))
async def handle_like(call: types.CallbackQuery):
    code = call.data.split("_")[1]
    action = call.data.split("_")[2]
    if action == "up": cursor.execute('UPDATE movies SET likes = likes + 1 WHERE code = ?', (code,))
    else: cursor.execute('UPDATE movies SET dislikes = dislikes + 1 WHERE code = ?', (code,))
    conn.commit()
    await call.answer("✅ Ovoz berdingiz!")

@dp.callback_query(F.data.startswith("report_"))
async def handle_report(call: types.CallbackQuery):
    code = call.data.split("_")[1]
    for admin in ADMINS:
        try: await bot.send_message(admin, f"⚠️ Shikoyat: Kino kodi {code} (User: {call.from_user.id})")
        except: pass
    await call.answer("✅ Shikoyat yuborildi!")

@dp.message(F.text == "👤 Profil")
async def profile(message: types.Message):
    cursor.execute('SELECT viewed_count FROM users WHERE user_id = ?', (message.from_user.id,))
    res = cursor.fetchone()
    count = res[0] if res else 0
    await message.answer(f"👤 Sizning profilingiz\n🎬 Ko'rilgan kinolar soni: {count}")

@dp.message(F.text == "⭐ TOP 10")
async def top_movies(message: types.Message):
    cursor.execute('SELECT code, likes FROM movies ORDER BY likes DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = "⭐ TOP 10 eng yaxshi kinolar:\n\n"
    for i, m in enumerate(movies, 1): text += f"{i}. 🎬 Kod: {m[0]} | 👍 {m[1]}\n"
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
        try: await bot.send_message(user[0], message.text)
        except: continue
    await message.answer("✅ Yuborildi!", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    await message.answer("📹 Videoni yuboring:")
    await state.set_state(AddMovie.file_id)

@dp.message(AddMovie.file_id, F.video | F.document)
async def get_video(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    await state.update_data(file_id=file_id)
    await message.answer("🔢 Kodini yozing:")
    await state.set_state(AddMovie.code)

@dp.message(AddMovie.code)
async def get_code(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text)
    await message.answer("📝 Endi kinosining tavsifini yozing:")
    await state.set_state(AddMovie.description)

@dp.message(AddMovie.description)
async def get_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute('INSERT OR REPLACE INTO movies (code, file_id, description) VALUES (?, ?, ?)', (data['code'], data['file_id'], message.text))
    conn.commit()
    await message.answer("✅ Saqlandi!", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "🗑 Kino o'chirish")
async def del_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    await message.answer("❌ O'chirmoqchi bo'lgan kodni yozing:")
    await state.set_state(DelMovie.code)

@dp.message(DelMovie.code)
async def delete_process(message: types.Message, state: FSMContext):
    cursor.execute('DELETE FROM movies WHERE code = ?', (message.text,))
    conn.commit()
    await message.answer("✅ O'chirildi!", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "🔥 Tasodifiy kino")
async def random_movie(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies ORDER BY RANDOM() LIMIT 1')
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍 {res[3]}", callback_data=f"like_{res[0]}_up"), InlineKeyboardButton(text=f"👎 {res[4]}", callback_data=f"like_{res[0]}_down")],
            [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{res[0]}")]
        ])
        await bot.send_video(message.chat.id, res[1], caption=f"✨ {res[2]}\n\n🎬 Kod: {res[0]}", reply_markup=kb)
    else: await message.answer("❌ Bazada hali kino yo'q.")

# --- МОДЕРНИЗИРОВАННЫЙ ПОИСК (ИЩЕТ СЕРИАЛЫ, А ПОТОМ ФИЛЬМЫ) ---
@dp.message(F.text)
async def search_movie(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
    
    # 1. Поиск сериала
    cursor.execute('SELECT title FROM serials WHERE code = ?', (message.text,))
    ser = cursor.fetchone()
    if ser:
        cursor.execute('SELECT ep_num FROM episodes WHERE code = ? ORDER BY ep_num ASC', (message.text,))
        eps = cursor.fetchall()
        kb_ep = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Qism {e[0]}", callback_data=f"ep_{message.text}_{e[0]}")] for e in eps
        ])
        await message.answer(f"🎬 Serial: {ser[0]}\nQismni tanlang:", reply_markup=kb_ep)
        return

    # 2. Поиск фильма (твой старый код)
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies WHERE code = ?', (message.text,))
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍 {res[3]}", callback_data=f"like_{res[0]}_up"), InlineKeyboardButton(text=f"👎 {res[4]}", callback_data=f"like_{res[0]}_down")],
            [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{res[0]}")]
        ])
        await bot.send_video(message.chat.id, res[1], caption=f"{res[2]}\n\n🎬 Kod: {message.text}", reply_markup=kb)
    else: await message.answer("❌ Topilmadi.")

async def run_web():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()

async def main():
    await run_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
