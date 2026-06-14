import asyncio
import sqlite3
import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)

# Твой ТОКЕН и ID канала
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412 # Теперь тут твой новый ID
ADMINS = [8350819510]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Подключение БД
conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT)')
conn.commit()

class AddMovie(StatesGroup):
    file_id = State()
    code = State()

async def is_subscribed(user_id):
    try:
        # Проверка статуса пользователя в канале
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        # Статусы, которые означают, что человек подписан
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

@dp.message(Command("start"))
async def start(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url="https://t.me/+PpgAdF1iQ8xhODEy")],
            [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")]
        ])
        await message.answer("👋 Salom! Botdan foydalanish uchun kanalimizga obuna bo'ling:", reply_markup=kb)
    else:
        await message.answer("🎬 Kino kodini yuboring va filmni tomosha qiling!")

@dp.callback_query(F.data == "check_sub")
async def check_sub(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.answer("✅ Rahmat! Obuna tasdiqlandi. Endi kino kodini yuboring.")
    else:
        await call.answer("❌ Siz hali kanalga obuna bo'lmagansiz!", show_alert=True)

@dp.message(F.video)
async def get_video(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMINS:
        await state.update_data(file_id=message.video.file_id)
        await message.answer("✅ Video qabul qilindi. Endi kodini yozing:")
        await state.set_state(AddMovie.code)

@dp.message(AddMovie.code)
async def get_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute('INSERT OR REPLACE INTO movies (code, file_id) VALUES (?, ?)', (message.text, data['file_id']))
    conn.commit()
    await message.answer(f"✅ Kino saqlandi! Kod: {message.text}")
    await state.clear()

@dp.message(F.text)
async def search_movie(message: types.Message):
    # Проверка подписки перед выдачей фильма
    if not await is_subscribed(message.from_user.id):
        await message.answer("❌ Botdan foydalanish uchun kanalga obuna bo'ling!")
        return
    
    cursor.execute('SELECT file_id FROM movies WHERE code = ?', (message.text,))
    res = cursor.fetchone()
    if res:
        await bot.send_video(message.chat.id, res[0], caption=f"🎬 Siz so'ragan kino: {message.text}")
    else:
        await message.answer("❌ Kino topilmadi. Kodni tekshiring.")

# UptimeRobot блок
async def handle(request): return web.Response(text="Bot is running")
async def run_web():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()

async def main():
    await run_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
