import asyncio
import sqlite3
import os
import logging
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

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()

# Таблицы
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS user_history (user_id INTEGER, film_code TEXT, viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
cursor.execute('CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, film_code TEXT, PRIMARY KEY (user_id, film_code))')
cursor.execute('CREATE TABLE IF NOT EXISTS series (code TEXT, series_number INTEGER, file_id TEXT, description TEXT, PRIMARY KEY (code, series_number))')
cursor.execute('CREATE TABLE IF NOT EXISTS series_progress (user_id INTEGER, series_code TEXT, last_series INTEGER DEFAULT 1, PRIMARY KEY (user_id, series_code))')
conn.commit()

# Состояния
class AddMovie(StatesGroup):
    file_id = State()
    code = State()
    description = State()

class Mailing(StatesGroup):
    text = State()

class DelMovie(StatesGroup):
    code = State()

class AddSeries(StatesGroup):
    code = State()
    file_id = State()
    description = State()
    another = State()

# Клавиатуры
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="🎬 Serial qo'shish"), KeyboardButton(text="🗑 Serial o'chirish")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📊 Detallar")],
    [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🔥 Tasodifiy kino")],
    [KeyboardButton(text="⭐ TOP 10"), KeyboardButton(text="📜 Tarix")],
    [KeyboardButton(text="❤️ Izlanganlar"), KeyboardButton(text="👤 Profil")],
    [KeyboardButton(text="❌ Bekor qilish")]
], resize_keyboard=True)

user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="📜 Tarix"), KeyboardButton(text="❤️ Izlanganlar")],
    [KeyboardButton(text="👤 Profil"), KeyboardButton(text="❌ Bekor qilish")]
], resize_keyboard=True)

async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# START
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
    await message.answer(f"👤 Profil\n🎬 Ko'rilgan: {count}")

@dp.message(F.text == "⭐ TOP 10")
async def top_movies(message: types.Message):
    cursor.execute('SELECT code, likes FROM movies ORDER BY likes DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kino yo'q.")
        return
    text = "⭐ TOP 10:\n\n"
    for i, m in enumerate(movies, 1):
        text += f"{i}. 🎬 {m[0]} | 👍 {m[1]}\n"
    await message.answer(text)

@dp.message(F.text == "📊 Statistika")
async def stats(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    await message.answer(f"👥 Foydalanuvchilar: {count}")

@dp.message(F.text == "📊 Detallar")
async def detailed_stats(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    cursor.execute('SELECT COUNT(*) FROM movies')
    total_movies = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(likes) FROM movies')
    total_likes = cursor.fetchone()[0] or 0
    cursor.execute('SELECT COUNT(DISTINCT code) FROM series')
    total_series = cursor.fetchone()[0] or 0
    await message.answer(f"📊 Detallar:\n🎬 Kinolar: {total_movies}\n📺 Seriallar: {total_series}\n👍 Layklar: {total_likes}")

@dp.message(F.text == "📢 Xabar yuborish")
async def mailing_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
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

@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
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
    await message.answer("📝 Tavsif yozing:")
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
    if message.from_user.id not in ADMINS:
        return
    await message.answer("❌ Kodni yozing:")
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
        cursor.execute('INSERT INTO user_history (user_id, film_code) VALUES (?, ?)', (message.from_user.id, res[0]))
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍 {res[3]}", callback_data=f"like_{res[0]}_up"), InlineKeyboardButton(text=f"👎 {res[4]}", callback_data=f"like_{res[0]}_down")],
            [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{res[0]}")]
        ])
        await bot.send_video(message.chat.id, res[1], caption=f"✨ {res[2]}\n\n🎬 Kod: {res[0]}", reply_markup=kb)
    else:
        await message.answer("❌ Kino yo'q.")

@dp.message(F.text == "📜 Tarix")
async def show_history(message: types.Message):
    cursor.execute('SELECT film_code, viewed_at FROM user_history WHERE user_id = ? ORDER BY viewed_at DESC LIMIT 10', (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("📭 Tarix bo'sh.")
        return
    text = "📜 So'nggi 10 ta:\n\n"
    for i, (code, dt) in enumerate(rows, 1):
        text += f"{i}. `{code}` — {dt[:16]}\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "❤️ Izlanganlar")
async def list_favorites(message: types.Message):
    cursor.execute('SELECT film_code FROM favorites WHERE user_id = ?', (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("❤️ Izlanganlar yo'q. /addfav KOD")
        return
    codes = [row[0] for row in rows]
    await message.answer(f"❤️ Izlanganlar:\n{', '.join(codes)}")

@dp.message(Command("addfav"))
async def add_favorite(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ /addfav KOD")
        return
    code = parts[1]
    cursor.execute('SELECT code FROM movies WHERE code = ?', (code,))
    if not cursor.fetchone():
        await message.answer("❌ Bunday kino yo'q.")
        return
    cursor.execute('INSERT OR IGNORE INTO favorites VALUES (?, ?)', (message.from_user.id, code))
    conn.commit()
    await message.answer(f"✅ {code} qo'shildi.")

@dp.message(Command("removefav"))
async def remove_favorite(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ /removefav KOD")
        return
    code = parts[1]
    cursor.execute('DELETE FROM favorites WHERE user_id = ? AND film_code = ?', (message.from_user.id, code))
    conn.commit()
    await message.answer(f"✅ {code} o'chirildi.")

@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    kb = admin_kb if message.from_user.id in ADMINS else user_kb
    await message.answer("❌ Bekor qilindi.", reply_markup=kb)

@dp.message(Command("backup"))
async def backup_db(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("⏳ Bazani yuklayapman...")
    conn.close()
    try:
        await bot.send_document(message.chat.id, FSInputFile('movies.db', filename='movies_backup.db'))
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
    finally:
        global conn, cursor
        conn = sqlite3.connect('movies.db', check_same_thread=False)
        cursor = conn.cursor()

@dp.message(F.text == "🎬 Serial qo'shish")
async def add_series_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📺 Serial kodini kiriting:")
    await state.set_state(AddSeries.code)

@dp.message(AddSeries.code)
async def add_series_code(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await message.answer("📹 1-seriyani yuboring:")
    await state.set_state(AddSeries.file_id)

@dp.message(AddSeries.file_id, F.video | F.document)
async def add_series_video(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    await state.update_data(file_id=file_id)
    await message.answer("📝 Tavsif (yoki '-'):")
    await state.set_state(AddSeries.description)

@dp.message(AddSeries.description)
async def add_series_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = message.text if message.text != "-" else ""
    cursor.execute('SELECT MAX(series_number) FROM series WHERE code = ?', (data['code'],))
    max_num = cursor.fetchone()[0] or 0
    series_num = max_num + 1
    cursor.execute('INSERT INTO series VALUES (?, ?, ?, ?)', (data['code'], series_num, data['file_id'], desc))
    cursor.execute('INSERT OR IGNORE INTO movies (code, file_id, description, likes, dislikes) VALUES (?, ?, ?, 0, 0)', (data['code'], data['file_id'], f"Serial: {data['code']}"))
    conn.commit()
    await message.answer(f"✅ {series_num}-seriya saqlandi. Yana? (ha/yo'q)")
    await state.set_state(AddSeries.another)

@dp.message(AddSeries.another)
async def add_series_another(message: types.Message, state: FSMContext):
    if message.text.lower() in ["ha", "yes", "y"]:
        await state.set_state(AddSeries.file_id)
        await message.answer("📹 Keyingi seriyani yuboring:")
    else:
        await state.clear()
        await message.answer("✅ Serial saqlandi!", reply_markup=admin_kb)

@dp.message(F.text == "🗑 Serial o'chirish")
async def del_series_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("❌ Serial kodini yozing:")
    await state.set_state(DelMovie.code)

@dp.message(F.text)
async def search_movie(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
    
    code = message.text.strip()
    
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies WHERE code = ?', (code,))
    res = cursor.fetchone()
    
    if res:
        cursor.execute('INSERT INTO user_history (user_id, film_code) VALUES (?, ?)', (message.from_user.id, code))
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍 {res[3]}", callback_data=f"like_{code}_up"), InlineKeyboardButton(text=f"👎 {res[4]}", callback_data=f"like_{code}_down")],
            [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{code}")]
        ])
        await bot.send_video(message.chat.id, res[1], caption=f"{res[2]}\n\n🎬 Kod: {code}", reply_markup=kb)
        return
    
    cursor.execute('SELECT COUNT(*) FROM series WHERE code = ?', (code,))
    if cursor.fetchone()[0] > 0:
        cursor.execute('SELECT last_series FROM series_progress WHERE user_id = ? AND series_code = ?', (message.from_user.id, code))
        prog = cursor.fetchone()
        current = prog[0] if prog else 1
        cursor.execute('SELECT file_id, description, (SELECT MAX(series_number) FROM series WHERE code = ?) FROM series WHERE code = ? AND series_number = ?', (code, code, current))
        s_res = cursor.fetchone()
        if s_res:
            cursor.execute('INSERT INTO user_history (user_id, film_code) VALUES (?, ?)', (message.from_user.id, f"{code}#{current}"))
            cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
            conn.commit()
            nav_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️", callback_data=f"series_{code}_prev"), InlineKeyboardButton(text="▶️", callback_data=f"series_{code}_next")],
                [InlineKeyboardButton(text="📋 Seriyalar", callback_data=f"series_{code}_list")]
            ])
            cursor.execute('SELECT likes, dislikes FROM movies WHERE code = ?', (code,))
            likes = cursor.fetchone()
            like_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"👍 {likes[0] if likes else 0}", callback_data=f"like_{code}_up"), InlineKeyboardButton(text=f"👎 {likes[1] if likes else 0}", callback_data=f"like_{code}_down")],
                [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{code}")]
            ])
            full_kb = InlineKeyboardMarkup(inline_keyboard=nav_kb.inline_keyboard + like_kb.inline_keyboard)
            await bot.send_video(message.chat.id, s_res[0], caption=f"🎬 {code}\n🔸 {current}/{s_res[2]} seriya\n{s_res[1] if s_res[1] else ''}", reply_markup=full_kb)
        else:
            await message.answer("❌ Seriya topilmadi.")
    else:
        await message.answer("❌ Topilmadi.")

@dp.callback_query(F.data.startswith("series_"))
async def series_navigate(call: types.CallbackQuery):
    parts = call.data.split("_")
    code = parts[1]
    action = parts[2]
    
    cursor.execute('SELECT last_series FROM series_progress WHERE user_id = ? AND series_code = ?', (call.from_user.id, code))
    prog = cursor.fetchone()
    current = prog[0] if prog else 1
    cursor.execute('SELECT MAX(series_number) FROM series WHERE code = ?', (code,))
    max_series = cursor.fetchone()[0] or 1
    
    if action == "prev":
        new_series = max(1, current - 1)
    elif action == "next":
        new_series = min(max_series, current + 1)
    elif action == "list":
        cursor.execute('SELECT series_number, description FROM series WHERE code = ? ORDER BY series_number', (code,))
        series_list = cursor.fetchall()
        text = f"📋 {code} seriyalari:\n\n"
        for num, desc in series_list:
            text += f"🔸 {num}-seriya"
            if desc:
                text += f": {desc[:50]}"
            text += "\n"
        await call.message.edit_caption(caption=text, reply_markup=None)
        await call.answer()
        return
    else:
        await call.answer()
        return
    
    cursor.execute('INSERT OR REPLACE INTO series_progress VALUES (?, ?, ?)', (call.from_user.id, code, new_series))
    conn.commit()
    
    cursor.execute('SELECT file_id, description FROM series WHERE code = ? AND series_number = ?', (code, new_series))
    s_res = cursor.fetchone()
    if not s_res:
        await call.answer("Seriya topilmadi")
        return
    
    nav_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️", callback_data=f"series_{code}_prev"), InlineKeyboardButton(text="▶️", callback_data=f"series_{code}_next")],
        [InlineKeyboardButton(text="📋 Seriyalar", callback_data=f"series_{code}_list")]
    ])
    cursor.execute('SELECT likes, dislikes FROM movies WHERE code = ?', (code,))
    likes = cursor.fetchone()
    like_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👍 {likes[0] if likes else 0}", callback_data=f"like_{code}_up"), InlineKeyboardButton(text=f"👎 {likes[1] if likes else 0}", callback_data=f"like_{code}_down")],
        [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report_{code}")]
    ])
    full_kb = InlineKeyboardMarkup(inline_keyboard=nav_kb.inline_keyboard + like_kb.inline_keyboard)
    
    await call.message.edit_caption(caption=f"🎬 {code}\n🔸 {new_series}/{max_series} seriya\n{s_res[1] if s_res[1] else ''}", reply_markup=full_kb)
    await call.answer()

# Запуск
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
