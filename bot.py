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
 
conn = sqlite3.connect('movies.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS movies (code TEXT PRIMARY KEY, file_id TEXT, description TEXT, likes INTEGER DEFAULT 0, dislikes INTEGER DEFAULT 0, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, viewed_count INTEGER DEFAULT 0)')
cursor.execute('CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, code TEXT, PRIMARY KEY(user_id, code))')
cursor.execute('CREATE TABLE IF NOT EXISTS series (series_code TEXT, episode_num INTEGER, file_id TEXT, description TEXT, PRIMARY KEY(series_code, episode_num))')
conn.commit()
 
class AddMovie(StatesGroup):
    file_id = State()
    code = State()
    description = State()
 
class Mailing(StatesGroup):
    text = State()
 
class DelMovie(StatesGroup):
    code = State()
 
class AddSeries(StatesGroup):
    series_code = State()
    description = State()
    episode_video = State()
 
# Клавиатуры
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="📺 Serial qo'shish")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="👤 Profil")]
], resize_keyboard=True)
 
user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="👤 Profil")]
], resize_keyboard=True)
 
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
        [InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"like|{code}|up"), InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"like|{code}|down")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav|{code}")],
        [InlineKeyboardButton(text="⚠️ Shikoyat", callback_data=f"report|{code}")]
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
    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text=fav_text, callback_data=f"favseries|{series_code}|{ep_num}")]
    ])
 
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
 
@dp.callback_query(F.data == "noop")
async def noop(call: types.CallbackQuery):
    await call.answer()
 
@dp.callback_query(F.data.startswith("like|"))
async def handle_like(call: types.CallbackQuery):
    _, code, action = call.data.split("|")
    if action == "up": cursor.execute('UPDATE movies SET likes = likes + 1 WHERE code = ?', (code,))
    else: cursor.execute('UPDATE movies SET dislikes = dislikes + 1 WHERE code = ?', (code,))
    conn.commit()
    await call.answer("✅ Ovoz berdingiz!")
 
@dp.callback_query(F.data.startswith("report|"))
async def handle_report(call: types.CallbackQuery):
    _, code = call.data.split("|")
    for admin in ADMINS:
        try: await bot.send_message(admin, f"⚠️ Shikoyat: Kino kodi {code} (User: {call.from_user.id})")
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
        except Exception:
            pass
 
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
        await call.message.edit_reply_markup(reply_markup=build_series_kb(series_code, int(ep_num), total_eps, user_id))
    except Exception:
        pass
 
@dp.callback_query(F.data.startswith("ep|"))
async def handle_episode_nav(call: types.CallbackQuery):
    _, series_code, ep_num = call.data.split("|")
    ep_num = int(ep_num)
    user_id = call.from_user.id
    cursor.execute('SELECT file_id, description FROM series WHERE series_code = ? AND episode_num = ?', (series_code, ep_num))
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
    except Exception:
        pass
    await bot.send_video(call.message.chat.id, file_id, caption=f"{description}\n\n🎬 Serial: {series_code} | {ep_num}-qism", reply_markup=kb)
    await call.answer()
 
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
 
@dp.message(F.text == "🆕 Yangi kinolar")
async def new_movies(message: types.Message):
    cursor.execute('SELECT code, description FROM movies ORDER BY added_at DESC LIMIT 10')
    movies = cursor.fetchall()
    if not movies:
        await message.answer("❌ Hali kinolar yo'q.")
        return
    text = "🆕 Yangi qo'shilgan kinolar:\n\n"
    for m in movies:
        desc = (m[1][:40] + "...") if len(m[1]) > 40 else m[1]
        text += f"🎬 Kod: {m[0]} — {desc}\n"
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
 
# ===== Сериалы (добавление админом) =====
@dp.message(F.text == "📺 Serial qo'shish")
async def add_series_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    await message.answer("🔢 Serial uchun kod kiriting (masalan: BREAKING_BAD):")
    await state.set_state(AddSeries.series_code)
 
@dp.message(AddSeries.series_code)
async def add_series_code(message: types.Message, state: FSMContext):
    await state.update_data(series_code=message.text.strip(), next_episode=1)
    await message.answer("📝 Serial uchun umumiy tavsif yozing (har bir qismda ko'rsatiladi):")
    await state.set_state(AddSeries.description)
 
@dp.message(AddSeries.description)
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
    cursor.execute('INSERT OR REPLACE INTO series (series_code, episode_num, file_id, description) VALUES (?, ?, ?, ?)',
                   (data['series_code'], ep_num, file_id, data['description']))
    conn.commit()
    await state.update_data(next_episode=ep_num + 1)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Yana qism qo'shish", callback_data="series_more")],
        [InlineKeyboardButton(text="✅ Tugatish", callback_data="series_done")]
    ])
    await message.answer(f"✅ {ep_num}-qism saqlandi! Davom etamizmi?", reply_markup=kb)
 
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
        conn.commit()
        kb = build_movie_kb(message.from_user.id, res[0], res[3], res[4])
        await bot.send_video(message.chat.id, res[1], caption=f"✨ {res[2]}\n\n🎬 Kod: {res[0]}", reply_markup=kb)
    else: await message.answer("❌ Bazada hali kino yo'q.")
 
@dp.message(F.text)
async def search_movie(message: types.Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("⚠️ Obuna bo'ling!")
        return
 
    text = message.text.strip()
 
    # Сначала проверяем — может это код сериала
    cursor.execute('SELECT file_id, description FROM series WHERE series_code = ? AND episode_num = 1', (text,))
    series_res = cursor.fetchone()
    if series_res:
        cursor.execute('SELECT COUNT(*) FROM series WHERE series_code = ?', (text,))
        total_eps = cursor.fetchone()[0]
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        file_id, description = series_res
        kb = build_series_kb(text, 1, total_eps, message.from_user.id)
        await bot.send_video(message.chat.id, file_id, caption=f"{description}\n\n🎬 Serial: {text} | 1-qism", reply_markup=kb)
        return
 
    # Иначе ищем как обычный фильм
    cursor.execute('SELECT code, file_id, description, likes, dislikes FROM movies WHERE code = ?', (text,))
    res = cursor.fetchone()
    if res:
        cursor.execute('UPDATE users SET viewed_count = viewed_count + 1 WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        kb = build_movie_kb(message.from_user.id, res[0], res[3], res[4])
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
