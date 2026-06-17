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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
 
logging.basicConfig(level=logging.INFO)
 
API_TOKEN = '8697886925:AAGJJwn-GfKWPGb4yoUzyA-ChTdURToQ1Ac'
CHANNEL_ID = -1004399893412
CHANNEL_URL = "https://t.me/+PpgAdF1iQ8xhODEy"
ADMINS = [8925518277, 8350819510]
 
# НОВОЕ: архивный канал для хранения видео навечно (бот должен быть админом в этом канале)
ARCHIVE_CHANNEL_ID = -1003788948077
 
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
 
conn = sqlite3.connect('movies.db', check_same_thread=False)
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
 
# ============================================================
# КЛАВИАТУРЫ (старые + новые кнопки)
# ============================================================
GENRES = {
    "action": "💥 Боевик",
    "comedy": "😂 Комедия",
    "drama": "🎭 Драма",
    "horror": "👻 Ужасы",
    "cartoon": "🎠 Мультфильм",
    "series": "📺 Сериал",
    "other": "🎬 Другое"
}
 
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
    [KeyboardButton(text="📺 Serial qo'shish"), KeyboardButton(text="📋 Barcha kinolar")],
    [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🔍 Qidirish")]
], resize_keyboard=True)
 
user_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Tasodifiy kino"), KeyboardButton(text="⭐ TOP 10")],
    [KeyboardButton(text="🆕 Yangi kinolar"), KeyboardButton(text="📁 Saqlanganlar")],
    [KeyboardButton(text="🎭 Janrlar"), KeyboardButton(text="🔍 Qidirish")],
    [KeyboardButton(text="📜 Tarix"), KeyboardButton(text="👤 Profil")]
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
        genre_emoji = GENRES.get(m[2], "🎬") if m[2] else "🎬"
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
 
@dp.message(Mailing.text)
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
    await message.answer("📹 Videoni yuboring:")
    await state.set_state(AddMovieNew.file_id)
 
@dp.message(AddMovieNew.file_id, F.video | F.document)
async def get_video_new(message: types.Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    await state.update_data(file_id=file_id)
    await message.answer("🔢 Kodini yozing:")
    await state.set_state(AddMovieNew.code)
 
@dp.message(AddMovieNew.code)
async def get_code_new(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text)
    await message.answer("📝 Kinosining tavsifini yozing:")
    await state.set_state(AddMovieNew.description)
 
@dp.message(AddMovieNew.description)
async def get_description_new(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=v, callback_data=f"setgenre|{k}")] for k, v in GENRES.items()
    ])
    await message.answer("🎭 Janrni tanlang:", reply_markup=kb)
    await state.set_state(AddMovieNew.genre)
 
@dp.callback_query(F.data.startswith("setgenre|"))
async def set_genre(call: types.CallbackQuery, state: FSMContext):
    genre = call.data.split("|")[1]
    data = await state.get_data()
    # НОВОЕ: дублируем видео в архивный канал, чтобы оно хранилось вечно
    archived_file_id = await archive_video(data['file_id'], caption=f"🎬 Kod: {data['code']}")
    cursor.execute('INSERT OR REPLACE INTO movies (code, file_id, description, genre) VALUES (?, ?, ?, ?)',
                  (data['code'], archived_file_id, data['description'], genre))
    conn.commit()
    await call.message.edit_text(f"✅ Kino saqlandi! Janr: {GENRES.get(genre)}")
    await bot.send_message(call.from_user.id, "👑 Admin panel:", reply_markup=admin_kb)
    await state.clear()
 
@dp.message(F.text == "🗑 Kino o'chirish")
async def del_movie(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("❌ O'chirmoqchi bo'lgan kodni yozing:")
    await state.set_state(DelMovie.code)
 
@dp.message(DelMovie.code)
async def delete_process(message: types.Message, state: FSMContext):
    cursor.execute('DELETE FROM movies WHERE code = ?', (message.text,))
    conn.commit()
    await message.answer("✅ O'chirildi!", reply_markup=admin_kb)
    await state.clear()
 
@dp.message(F.text == "📺 Serial qo'shish")
async def add_series_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🔢 Serial uchun kod kiriting (masalan: BREAKING_BAD):")
    await state.set_state(AddSeries.series_code)
 
@dp.message(AddSeries.series_code)
async def add_series_code(message: types.Message, state: FSMContext):
    await state.update_data(series_code=message.text.strip(), next_episode=1)
    await message.answer("📝 Serial uchun umumiy tavsif yozing:")
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
 
@dp.message(F.text)
async def search_movie(message: types.Message, state: FSMContext):
    # Пропускаем кнопки меню
    menu_texts = ["🎭 Janrlar", "🔍 Qidirish", "📜 Tarix", "📋 Barcha kinolar"]
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
        genre_emoji = GENRES.get(m[1], "🎬")
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
    cursor.execute('SELECT code, description FROM movies WHERE genre=? ORDER BY likes DESC LIMIT 10', (genre,))
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
 
@dp.message(SearchMovie.query)
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
        genre_emoji = GENRES.get(r[2], "🎬")
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
    genre = res[0]
    cursor.execute(
        'SELECT code, description FROM movies WHERE genre=? AND code!=? ORDER BY likes DESC LIMIT 5',
        (genre, code)
    )
    similar = cursor.fetchall()
    if not similar:
        await call.answer("❌ O'xshash kinolar topilmadi", show_alert=True)
        return
    text = f"📺 {GENRES.get(genre, 'Shunga o\'xshash')} janridagi kinolar:\n\n"
    for s in similar:
        desc = (s[1][:40] + "...") if len(s[1]) > 40 else s[1]
        text += f"🎬 Kod: {s[0]} — {desc}\n"
    await call.message.answer(text)
    await call.answer()
 
# ============================================================
# ВЕБ + ЗАПУСК
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
    await dp.start_polling(bot)
 
if __name__ == "__main__":
    asyncio.run(main())
