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

API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
ADMINS = [8925518277, 8350819510]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
conn.commit()

class AddMovie(StatesGroup):
    file_id = State()
    code = State()
    description = State()

class Mailing(StatesGroup):
    text = State()

class DelMovie(StatesGroup):
    code = State()

admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
    [KeyboardButton(text="🔥 Tasodifiy kino")]
], resize_keyboard=True)

@dp.message(Command("start"))
async def start(message: types.Message):
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (message.from_user.id,))
    conn.commit()
    if message.from_user.id in ADMINS:
        await message.answer("👑 Admin panel:", reply_markup=admin_kb)
    else:
        await message.answer("🎬 Kino kodini yuboring:")

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
    await message.answer("📝 Endi kinosining tavsifini (opisaniyasini) yozing:")
    await state.set_state(AddMovie.description)

@dp.message(AddMovie.description)
async def get_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute('INSERT OR REPLACE INTO movies (code, file_id, description) VALUES (?, ?, ?)', 
                   (data['code'], data['file_id'], message.text))
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
    cursor.execute('SELECT code, file_id, description FROM movies ORDER BY RANDOM() LIMIT 1')
    res = cursor.fetchone()
    if res: await bot.send_video(message.chat.id, res[1], caption=f"✨ {res[2]}\n\n🎬 Kod: {res[0]}")
    else: await message.answer("❌ Bazada hali kino yo'q.")

@dp.message(F.text)
async def search_movie(message: types.Message):
    cursor.execute('SELECT file_id, description FROM movies WHERE code = ?', (message.text,))
    res = cursor.fetchone()
    if res: await bot.send_video(message.chat.id, res[0], caption=f"{res[1]}\n\n🎬 Kod: {message.text}")
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
