import os
import logging
import asyncio
import psycopg2
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, LabeledPrice, PreCheckoutQuery

# Инициализация
API_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMINS = ["BLRPMM", "Lelouch_Vi_Britannia"]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- База данных (встроена) ---
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, username TEXT, gender TEXT, age INT, city TEXT, photo TEXT,
            tier TEXT DEFAULT 'Не оценен', vip_until TIMESTAMP DEFAULT '2000-01-01',
            likes_today INT DEFAULT 0, last_reset_date TEXT, is_banned INT DEFAULT 0, referrer_id BIGINT
        );
        CREATE TABLE IF NOT EXISTS ratings (id SERIAL PRIMARY KEY, from_user_id BIGINT, to_user_id BIGINT, tier_given TEXT);
        CREATE TABLE IF NOT EXISTS reports (id SERIAL PRIMARY KEY, from_user_id BIGINT, reported_user_id BIGINT, reason TEXT);
    """)
    conn.commit()
    conn.close()

# --- Состояния ---
class RegState(StatesGroup):
    gender = State(); age = State(); city = State(); photo = State()
class ReportState(StatesGroup):
    reason = State()

# --- Логика ---
def is_vip(uid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (uid,))
    res = cur.fetchone(); conn.close()
    return res and datetime.now() < res[0]

@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (msg.from_user.id,))
    if not cur.fetchone():
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Принять политику", callback_data="accept_policy")]])
        await msg.answer("Привет! Прими политику конфиденциальности, чтобы начать.", reply_markup=kb)
    else:
        await msg.answer("Ты уже зарегистрирован!")
    conn.close()

@dp.callback_query(F.data == "accept_policy")
async def policy(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚹 Мужской", callback_data="gen_male"),
        InlineKeyboardButton(text="🚺 Женский", callback_data="gen_female")
    ]])
    await cb.message.edit_text("Выбери пол:", reply_markup=kb)
    await state.set_state(RegState.gender)

@dp.callback_query(RegState.gender)
async def set_gen(cb: CallbackQuery, state: FSMContext):
    await state.update_data(gender="male" if "male" in cb.data else "female")
    await cb.message.edit_text("Сколько тебе лет? (12-30)")
    await state.set_state(RegState.age)

@dp.message(RegState.age)
async def set_age(msg: Message, state: FSMContext):
    if not msg.text.isdigit() or not (12 <= int(msg.text) <= 30):
        return await msg.answer("Введите корректный возраст (12-30)")
    await state.update_data(age=msg.text)
    await msg.answer("Какой твой город?")
    await state.set_state(RegState.city)

@dp.message(RegState.city)
async def set_city(msg: Message, state: FSMContext):
    await state.update_data(city=msg.text)
    await msg.answer("Пришли фото лица:")
    await state.set_state(RegState.photo)

@dp.message(RegState.photo, F.photo)
async def set_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username, gender, age, city, photo) VALUES (%s, %s, %s, %s, %s, %s)",
                (msg.from_user.id, msg.from_user.username, data['gender'], int(data['age']), data['city'], msg.photo[-1].file_id))
    conn.commit(); conn.close(); await state.clear()
    await msg.answer("Регистрация завершена! Используй /start для меню.")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
