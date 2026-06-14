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
CHANNEL_URL = "https://t.me/A_ToolsX"
ADMINS = [8925518277, 8350819510]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Инициализация БД
conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT)')
conn.commit()

async def is_subscribed(user_id):
    if user_id in ADMINS: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

@dp.message(Command("start"))
async def start(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Проверить", callback_data="check")]
        ])
        return await message.answer("⚠️ Для работы с ботом подпишись на канал:", reply_markup=kb)
    
    await message.answer("🎬 Введи код фильма:")

@dp.callback_query(F.data == "check")
async def check(call: types.CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.answer("✅ Подписка подтверждена! Введи код фильма.")
    else:
        await call.answer("❌ Ты еще не подписан!", show_alert=True)

@dp.message(F.text)
async def search(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        return await message.answer("⚠️ Сначала подпишись!")

    # Админ-команда добавления (упрощено)
    if message.text.startswith("/add") and message.from_user.id in ADMINS:
        # Пример: /add код,file_id,описание
        parts = message.text.split(",")
        code = parts[0].replace("/add ", "")
        cursor.execute('INSERT OR REPLACE INTO movies VALUES (?, ?, ?)', (code, parts[1], parts[2]))
        conn.commit()
        return await message.answer("✅ Добавлено!")

    # Поиск
    cursor.execute('SELECT file_id, description FROM movies WHERE code = ?', (message.text,))
    res = cursor.fetchone()
    if res:
        await bot.send_video(message.chat.id, res[0], caption=res[1])
    else:
        await message.answer("❌ Фильм не найден.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
