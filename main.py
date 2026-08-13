import asyncio
import logging
import os
from datetime import datetime, timedelta
from collections import Counter

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import asyncpg
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Получение переменных окружения
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id.strip()]

bot = Bot(token=TOKEN)
dp = Dispatcher()
db_pool = None

# Состояния FSM
class Registration(StatesGroup):
    waiting_for_age = State()
    waiting_for_gender = State()
    waiting_for_photo = State()

class AdminReportState(StatesGroup):
    waiting_for_ban_reason = State()

class AdminState(StatesGroup):
    waiting_for_username = State()
    waiting_for_days = State()

async def check_admin(user: types.User) -> bool:
    return user.id in ADMIN_IDS

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", message.from_user.id)
        
    if user and user['photo_id']:
        await message.answer("👋 С возвращением! Вы уже зарегистрированы. Используйте /rate для оценки анкет.")
        return

    await message.answer("👋 Добро пожаловать! Давайте создадим вашу анкету.\n\nСколько вам лет? (Введите число):")
    await state.set_state(Registration.waiting_for_age)

@dp.message(Registration.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (10 <= int(message.text) <= 100):
        await message.answer("⚠️ Пожалуйста, введите корректный возраст (число от 10 до 100):")
        return
    
    await state.update_data(age=int(message.text))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👨 Мужской", callback_data="gender_male"),
            InlineKeyboardButton(text="👩 Женский", callback_data="gender_female")
        ]
    ])
    await message.answer("🚻 Выберите ваш пол:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_gender)

@dp.callback_query(F.data.startswith("gender_"))
async def process_gender(callback: types.CallbackQuery, state: FSMContext):
    gender = "Мужской" if callback.data == "gender_male" else "Женский"
    await state.update_data(gender=gender)
    
    await callback.message.answer("📸 Отправьте фотографию для вашей анкеты:")
    await state.set_state(Registration.waiting_for_photo)
    await callback.answer()

@dp.message(Registration.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    
    user_id = message.from_user.id
    username = message.from_user.username
    age = data.get("age")
    gender = data.get("gender")

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, age, gender, photo_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = $2, age = $3, gender = $4, photo_id = $5
        """, user_id, username, age, gender, photo_id)

    await message.answer("✅ Регистрация успешно завершена! Теперь вы можете оценивать других с помощью команды /rate.")
    await state.clear()

@dp.message(Registration.waiting_for_photo, ~F.photo)
async def process_photo_invalid(message: types.Message):
    await message.answer("⚠️ Пожалуйста, отправьте именно фотографию (картинку).")

@dp.message(Command("rate"))
async def cmd_rate(message: types.Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user or not user['photo_id']:
            await message.answer("❌ У вас нет активной анкеты. Зарегистрируйтесь заново через /start")
            return

        target = await conn.fetchrow("""
            SELECT * FROM users 
            WHERE user_id != $1 AND photo_id IS NOT NULL 
            AND user_id NOT IN (SELECT target_id FROM ratings WHERE voter_id = $1)
            ORDER BY RANDOM() LIMIT 1
        """, user_id)

    if not target:
        await message.answer("😔 Больше нет анкет для оценки. Попробуйте позже!")
        return

    caption = f"👤 Возраст: {target['age']}\n🚻 Пол: {target['gender']}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👎 Sub 3", callback_data=f"rate_{target['user_id']}_sub 3"),
            InlineKeyboardButton(text="👎 Sub 5", callback_data=f"rate_{target['user_id']}_sub 5")
        ],
        [
            InlineKeyboardButton(text="⚖️ Ltn/Ltb", callback_data=f"rate_{target['user_id']}_ltn"),
            InlineKeyboardButton(text="⚖️ Mtn/Mtb", callback_data=f"rate_{target['user_id']}_mtn")
        ],
        [
            InlineKeyboardButton(text="👍 Htn/Htb", callback_data=f"rate_{target['user_id']}_htn"),
            InlineKeyboardButton(text="🔥 Chad/Stacy", callback_data=f"rate_{target['user_id']}_chad")
        ],
        [
            InlineKeyboardButton(text="🚨 Пожаловаться", callback_data=f"report_{target['user_id']}")
        ]
    ])

    await message.answer_photo(photo=target['photo_id'], caption=caption, reply_markup=kb)

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    target_id = int(data_parts[1])
    score = "_".join(data_parts[2:])
    voter_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO ratings (voter_id, target_id, score)
            VALUES ($1, $2, $3)
            ON CONFLICT (voter_id, target_id) DO UPDATE SET score = $3
        """, voter_id, target_id, score)

    await callback.answer("✅ Оценка учтена!")
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Вызов следующей анкеты
    fake_message = callback.message
    fake_message.from_user = callback.from_user
    await cmd_rate(fake_message)

@dp.callback_query(F.data.startswith("report_"))
async def process_report_start(callback: types.CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target_id=target_id, report_message_id=callback.message.message_id)
    await callback.message.answer("✍️ Напишите причину жалобы:")
    await state.set_state(AdminReportState.waiting_for_ban_reason) # Используем временный ввод причины
    await callback.answer()

@dp.message(AdminReportState.waiting_for_ban_reason)
async def process_report_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Проверяем, откуда прилетело состояние (жалоба или бан админом)
    if "report_target_id" in data:
        target_id = data.get("report_target_id")
        reason = message.text
        voter_id = message.from_user.id

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO reports (target_id, voter_id, reason)
                VALUES ($1, $2, $3)
            """, target_id, voter_id, reason)

        await message.answer("🚨 Жалоба успешно отправлена администраторам.")
        await state.clear()
        
        try:
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"🚨 Новая жалоба на пользователя `{target_id}` от `{voter_id}`.\nПричина: {reason}", parse_mode="Markdown")
        except Exception:
            pass
        return

    # Если это была админская панель удаления по жалобе
    report_id = data.get("ban_report_id")
    target_id = data.get("ban_target_id")
    reason = message.text

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET photo_id = NULL WHERE user_id = $1", target_id)
        await conn.execute("DELETE FROM reports WHERE id = $1", report_id)
        await conn.execute("INSERT INTO accepted_reports (accepted_at) VALUES (NOW())")

    try:
        await bot.send_message(
            chat_id=target_id, 
            text=f"⚠️ **Ваша анкета была удалена администратором.**\n\n💬 **Причина:** {reason}\n\nВы можете зарегистрироваться заново с помощью /start."
        )
    except Exception:
        pass

    await message.answer(f"✅ Жалоба №{report_id} принята. Анкета пользователя `{target_id}` сброшена.")
    await state.clear()

# =================== 👑 АДМИН ПАНЕЛЬ 👑 ===================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await check_admin(message.from_user):
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users_1")],
        [InlineKeyboardButton(text="🚨 Жалобы", callback_data="adm_reports_1")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="🎁 Выдать ВИП", callback_data="adm_give_vip")]
    ])
    await message.answer("👑 **Панель администратора:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "adm_stats")
async def adm_show_stats(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user): 
        await callback.answer("Ошибка доступа", show_alert=True)
        return

    async with db_pool.acquire() as conn:
        new_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '1 day'") or 0
        new_reports = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE created_at >= NOW() - INTERVAL '1 day'") or 0
        accepted_reports = await conn.fetchval("SELECT COUNT(*) FROM accepted_reports WHERE accepted_at >= NOW() - INTERVAL '1 day'") or 0
        ratings_count = await conn.fetchval("SELECT COUNT(*) FROM ratings WHERE created_at >= NOW() - INTERVAL '1 day'") or 0

        tier_rows = await conn.fetch("SELECT score FROM ratings WHERE created_at >= NOW() - INTERVAL '1 day'")
        
    tier_counts = Counter()
    for row in tier_rows:
        s = row['score'].lower()
        if "sub 3" in s: tier_counts["sub 3"] += 1
        elif "sub 5" in s: tier_counts["sub 5"] += 1
        elif "ltn" in s: tier_counts["ltn/ltb"] += 1
        elif "mtn" in s: tier_counts["mtn/mtb"] += 1
        elif "htn" in s: tier_counts["htn/htb"] += 1
        elif "chad" in s: tier_counts["chad/stacy"] += 1

    total_tiers = sum(tier_counts.values())

    def get_pct(key):
        if total_tiers == 0: return "0%"
        pct = (tier_counts[key] / total_tiers) * 100
        return f"{pct:.1f}%"

    stats_text = (
        f"📊 **Статистика за 24 часа:**\n\n"
        f"📝 Новых анкет: **{new_users}**\n"
        f"🚨 Жалоб: **{new_reports}**\n"
        f"✅ Принятых жалоб: **{accepted_reports}**\n"
        f"🔥 Оценок: **{ratings_count}**"
    )

    await callback.message.answer(stats_text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_reports_"))
async def adm_show_reports(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return

    page = int(callback.data.split("_")[2])
    limit = 1

    async with db_pool.acquire() as conn:
        reports = await conn.fetch("""
            SELECT r.id, r.target_id, r.voter_id, r.reason, u.photo_id, u.username
            FROM reports r
            LEFT JOIN users u ON r.target_id = u.user_id
            ORDER BY r.id DESC LIMIT $1 OFFSET $2
        """, limit, (page - 1) * limit)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM reports")

    if not reports:
        await callback.message.answer("📂 Жалоб пока нет!")
        await callback.answer()
        return

    r = reports[0]
    photo_id = r['photo_id']
    target_user = f"@{r['username']}" if r['username'] else f"ID: {r['target_id']}"

    caption = (
        f"🚨 **Жалоба №{r['id']}** (Всего: {total_count})\n\n"
        f"👤 На кого: {target_user} (`{r['target_id']}`)\n"
        f"🕵️ Кто пожаловался: `{r['voter_id']}`\n"
        f"💬 **Причина:** {r['reason'] or 'Не указана'}"
    )

    kb_buttons = [
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"adm_accept_rep_{r['id']}_{r['target_id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_decline_rep_{r['id']}")
        ]
    ]

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_reports_{page - 1}"))
    if page * limit < total_count:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm_reports_{page + 1}"))

    if nav_buttons:
        kb_buttons.append(nav_buttons)

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    if photo_id:
        await callback.message.answer_photo(photo=photo_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.answer(caption + "\n\n⚠️ *Фото профиля отсутствует или удалено*", reply_markup=kb, parse_mode="Markdown")

    await callback.answer()

@dp.callback_query(F.data.startswith("adm_decline_rep_"))
async def adm_decline_report(callback: types.CallbackQuery):
    report_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM reports WHERE id = $1", report_id)
    
    await callback.message.answer("❌ Жалоба отклонена и удалена.")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_accept_rep_"))
async def adm_accept_report_start(callback: types.CallbackQuery, state: FSMContext):
    _, _, _, report_id, target_id = callback.data.split("_")
    await state.update_data(ban_report_id=int(report_id), ban_target_id=int(target_id))
    await callback.message.answer("✍️ Напишите причину удаления анкеты (она будет отправлена пользователю):")
    await state.set_state(AdminReportState.waiting_for_ban_reason)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_users_"))
async def adm_show_users(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return

    page = int(callback.data.split("_")[2])
    limit = 10
    offset = (page - 1) * limit

    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username FROM users ORDER BY user_id ASC LIMIT $1 OFFSET $2", limit, offset)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM users")

    if not users:
        await callback.answer("На этой странице нет пользователей.", show_alert=True)
        return

    text = f"👥 **Список пользователей (Страница {page}):**\n\n"
    for i, u in enumerate(users, start=offset + 1):
        uname = f"@{u['username']}" if u['username'] else f"ID: `{u['user_id']}`"
        text += f"{i}. {uname}\n"

    total_pages = (total_count + limit - 1) // limit
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_users_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm_users_{page + 1}"))

    keyboard = [nav_buttons] if nav_buttons else []
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "adm_give_vip")
async def adm_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return
    await callback.message.answer("✏️ Введите @username пользователя (без знака @):")
    await state.set_state(AdminState.waiting_for_username)
    await callback.answer()

@dp.message(AdminState.waiting_for_username)
async def adm_get_username(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user):
        return
    username = message.text.replace("@", "").strip()
    await state.update_data(target_username=username)
    await message.answer("⏳ На сколько дней выдать ВИП? (введите число):")
    await state.set_state(AdminState.waiting_for_days)

@dp.message(AdminState.waiting_for_days)
async def adm_get_days(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user):
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число дней:")
        return
    
    days = int(message.text)
    data = await state.get_data()
    username = data.get("target_username")

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username)
        if not user:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            await state.clear()
            return

        now = datetime.now()
        start_date = user['vip_until'] if user['vip_until'] and user['vip_until'] > now else now
        new_vip = start_date + timedelta(days=days)
        
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", new_vip, user['user_id'])

    try:
        await bot.send_message(chat_id=user['user_id'], text=f"🎉 Вам выдан 💎 **ВИП на {days} дней**!")
    except Exception:
        pass

    await message.answer(f"✅ ВИП успешно выдан пользователю @{username} на {days} дней!")
    await state.clear()

async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                age INT,
                gender TEXT,
                photo_id TEXT,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS ratings (
                voter_id BIGINT,
                target_id BIGINT,
                score TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (voter_id, target_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                target_id BIGINT,
                voter_id BIGINT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS accepted_reports (
                id SERIAL PRIMARY KEY,
                accepted_at TIMESTAMP DEFAULT NOW()
            );
        """)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
