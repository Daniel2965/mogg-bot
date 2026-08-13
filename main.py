import asyncio
import logging
import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# Токен твоего бота
BOT_TOKEN = "8950068828:AAGGTOqKNHCGzLj-4VsfSjMe-ImLynRaNKg"

# Строка подключения к Neon PostgreSQL
DATABASE_URL = "postgresql://neondb_owner:npg_dynKuOEmo28X@ep-young-haze-axtbbubu-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require"

# Админы проекта
ADMIN_USERNAMES = ["BLRPMM"]
ADMIN_IDS = []

router = Router()

# Глобальная переменная для пула соединений с БД
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                name TEXT,
                age INT,
                gender TEXT,
                photo_id TEXT,
                status TEXT DEFAULT 'active',
                vip_days INT DEFAULT 0,
                invited_by BIGINT
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY,
                from_user_id BIGINT,
                to_user_id BIGINT,
                tier TEXT
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id SERIAL PRIMARY KEY,
                from_user_id BIGINT,
                target_user_id BIGINT,
                reason TEXT
            )
        """)


class RegStates(StatesGroup):
    age = State()
    gender = State()
    photo = State()

class AdminVipStates(StatesGroup):
    username = State()
    days = State()


# --- Клавиатуры ---

def get_main_menu_kb(user_id: int, username: str):
    kb = [
        [
            InlineKeyboardButton(text="⭐ Оценивать", callback_data="menu_rate"),
            InlineKeyboardButton(text="📄 Моя анкета", callback_data="menu_profile"),
        ],
        [
            InlineKeyboardButton(text="🏆 Топы", callback_data="menu_tops"),
            InlineKeyboardButton(text="💎 VIP", callback_data="menu_vip"),
        ],
        [
            InlineKeyboardButton(text="🔗 Реферальная программа", callback_data="menu_ref")
        ]
    ]
    if user_id in ADMIN_IDS or (username and username in ADMIN_USERNAMES):
        kb.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_age_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Закончить регистрацию", callback_data="cancel_reg")]])

def get_gender_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужчина", callback_data="gender_male"), InlineKeyboardButton(text="👩 Женщина", callback_data="gender_female")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reg")]
    ])

def get_photo_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Закончить регистрацию", callback_data="cancel_reg")]])

def get_profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ ❤️ Меня оценили", callback_data="my_ratings")],
        [InlineKeyboardButton(text="✏️ Изменить фото", callback_data="edit_photo")],
        [InlineKeyboardButton(text="✏️ Изменить возраст", callback_data="edit_age"), InlineKeyboardButton(text="✏️ Изменить пол", callback_data="edit_gender")],
        [InlineKeyboardButton(text="⭐ Кого оценивать", callback_data="menu_rate")],
        [InlineKeyboardButton(text="🌐 Язык / Language", callback_data="lang_settings")],
        [InlineKeyboardButton(text="🗑️ Удалить анкету", callback_data="delete_profile")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])

def get_rating_tiers_kb(target_user_id: int):
    tiers = ["Bad3", "Bad5", "Ltb", "Mtb", "Htb", "Stacy Lite", "Stacy", "True Eve"]
    buttons = []
    row = []
    for tier in tiers:
        row.append(InlineKeyboardButton(text=f"🌸 {tier}", callback_data=f"rate_{target_user_id}_{tier}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="💬 Хочу пообщаться", callback_data="chat_target")])
    buttons.append([InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"complaint_{target_user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="💎 Выдать VIP", callback_data="admin_give_vip")],
        [InlineKeyboardButton(text="🚩 Жалобы", callback_data="admin_complaints")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])


# --- Хэндлеры ---

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    args = message.text.split()

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT name, status FROM users WHERE user_id = $1", user_id)

        if not user and len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer_id = int(args[1].split("_")[1])
                if referrer_id != user_id:
                    await conn.execute("UPDATE users SET vip_days = vip_days + 1 WHERE user_id = $1", referrer_id)
            except ValueError:
                pass

        if user and user["status"] == "active":
            await message.answer("👋 Главное меню\nВыбирай раздел — здесь начинается самое интересное.", reply_markup=get_main_menu_kb(user_id, username))
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Политика конфиденциальности", url="https://telegram.org")],
        [InlineKeyboardButton(text="📄 Условия использования", url="https://telegram.org")],
        [InlineKeyboardButton(text="✅ Мне 14+, принимаю", callback_data="accept_rules")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reg")]
    ])
    await message.answer("🔒 **Подтверждение возраста и правил**\n\nПродолжая, ты подтверждаешь, что тебе уже исполнилось **14 лет**, и принимаешься Политику конфиденциальности и Условия использования.", reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "accept_rules")
async def accept_rules(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🎂 **Сколько тебе лет?**\n\nНапиши возраст одним числом от **14** до **99**.", reply_markup=get_age_kb(), parse_mode="Markdown")
    await state.set_state(RegStates.age)
    await callback.answer()

@router.message(RegStates.age)
async def process_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Пожалуйста, введи возраст числом от 14 до 99.")
        return
    age = int(message.text)
    if age < 14 or age > 99:
        await message.answer("⚠️ Возраст должен быть от 14 до 99 лет.")
        return

    await state.update_data(age=age)
    await message.answer("✨ **Выбери свой пол**", reply_markup=get_gender_kb(), parse_mode="Markdown")
    await state.set_state(RegStates.gender)

@router.callback_query(RegStates.gender, F.data.startswith("gender_"))
async def process_gender(callback: CallbackQuery, state: FSMContext):
    gender = "мужчина" if callback.data == "gender_male" else "женщина"
    await state.update_data(gender=gender)
    await callback.message.edit_text("📸 **Добавь главное фото**\n\nНа фотографии должно быть видно твоё лицо.", reply_markup=get_photo_kb(), parse_mode="Markdown")
    await state.set_state(RegStates.photo)
    await callback.answer()

@router.message(RegStates.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    age = data.get("age")
    gender = data.get("gender")
    user_id = message.from_user.id
    username = message.from_user.username or ""
    name = message.from_user.first_name or "Пользователь"

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, name, age, gender, photo_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'active')
            ON CONFLICT (user_id) DO UPDATE 
            SET username = $2, name = $3, age = $4, gender = $5, photo_id = $6, status = 'active'
        """, user_id, username, name, age, gender, photo_id)

    await state.clear()
    await message.answer(f"👤 Готово, {name}! Регистрация завершена.")
    await message.answer("⭐ Главное меню", reply_markup=get_main_menu_kb(user_id, message.from_user.username))

@router.callback_query(F.data == "cancel_reg")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Регистрация не пройдена. Напиши /start")
    await callback.answer()

@router.callback_query(F.data == "menu_profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT name, age, gender, photo_id, vip_days FROM users WHERE user_id = $1", user_id)

    if not user:
        await callback.message.answer("Анкета не найдена. Нажми /start")
        await callback.answer()
        return

    name, age, gender, photo_id, vip_days = user
    vip_text = f"активен (дней: {vip_days})" if vip_days > 0 else "не активен"
    caption = f"📄 **{name}**\nВозраст: {age}\nПол: {gender}\nVIP: {vip_text}"

    await callback.message.answer_photo(photo=photo_id, caption=caption, reply_markup=get_profile_kb(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "menu_rate")
async def start_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        target = await conn.fetchrow("SELECT user_id, name, age, photo_id FROM users WHERE user_id != $1 AND status = 'active' ORDER BY RANDOM() LIMIT 1", user_id)

    if not target:
        await callback.message.answer("😔 Пока нет доступных анкет для оценки.")
        await callback.answer()
        return

    t_id, t_name, t_age, t_photo = target["user_id"], target["name"], target["age"], target["photo_id"]
    caption = f"🌸 **{t_name}, {t_age}** · Средний тир: пока формируется\n\nКакой тир поставишь?"

    await callback.message.answer_photo(photo=t_photo, caption=caption, reply_markup=get_rating_tiers_kb(t_id), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("rate_"))
async def process_tier_rating(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    target_user_id = int(data_parts[1])
    tier = data_parts[2]
    from_user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO ratings (from_user_id, to_user_id, tier) VALUES ($1, $2, $3)", from_user_id, target_user_id, tier)

    await callback.answer(f"Ты поставил тир: {tier}!")
    await start_rating(callback)

@router.callback_query(F.data.startswith("complaint_"))
async def process_complaint_prompt(callback: CallbackQuery):
    target_user_id = int(callback.data.split("_")[1])
    from_user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO complaints (from_user_id, target_user_id, reason) VALUES ($1, $2, $3)", from_user_id, target_user_id, "Нарушение правил / Спам")

    await callback.answer("🚨 Жалоба успешно отправлена администрации!", show_alert=True)
    await start_rating(callback)

@router.callback_query(F.data == "menu_tops")
async def show_tops(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ недели", callback_data="top_week")],
        [InlineKeyboardButton(text="👑 Общий топ", callback_data="top_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    await callback.message.answer("📊 **Топы**", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "menu_vip")
async def show_vip(callback: CallbackQuery):
    text = "💎 **VIP Статус**\n\n⭐ 1 день — 10 Stars\n⭐ 7 дней — 49 Stars"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "menu_ref")
async def show_referral(callback: CallbackQuery):
    bot_info = await callback.bot.get_me()
    user_id = callback.from_user.id
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    text = f"🔗 **Реферальная ссылка**:\n`{ref_link}`"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.answer("⭐ Главное меню", reply_markup=get_main_menu_kb(callback.from_user.id, callback.from_user.username))
    await callback.answer()

# --- Админ-панель ---

@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS and callback.from_user.username not in ADMIN_USERNAMES:
        await callback.answer("У тебя нет доступа.", show_alert=True)
        return
    await callback.message.answer("👑 **Панель администратора**", reply_markup=get_admin_panel_kb(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_ratings = await conn.fetchval("SELECT COUNT(*) FROM ratings")
        total_complaints = await conn.fetchval("SELECT COUNT(*) FROM complaints")

    text = f"📊 **Статистика бота**\n\n👤 Создано анкет: **{total_users}**\n⭐ Поставлено оценок: **{total_ratings}**\n🚩 Подано жалоб: **{total_complaints}**"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel")]])
    await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_give_vip")
async def admin_give_vip_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💎 Введи юзернейм пользователя (например, `@username`):")
    await state.set_state(AdminVipStates.username)
    await callback.answer()

@router.message(AdminVipStates.username)
async def admin_vip_get_username(message: Message, state: FSMContext):
    await state.update_data(target_username=message.text.strip().lstrip("@"))
    await message.answer("🔢 Введи количество дней VIP:")
    await state.set_state(AdminVipStates.days)

@router.message(AdminVipStates.days)
async def admin_vip_get_days(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введи число.")
        return
    days = int(message.text)
    data = await state.get_data()
    target_username = data.get("target_username")

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id FROM users WHERE username = $1", target_username)
        if not user:
            await message.answer(f"❌ Пользователь @{target_username} не найден.")
            await state.clear()
            return
        await conn.execute("UPDATE users SET vip_days = vip_days + $1 WHERE user_id = $2", days, user["user_id"])

    await state.clear()
    await message.answer(f"✅ Успешно добавлено {days} дней VIP для @{target_username}!")

@router.callback_query(F.data == "admin_complaints")
async def admin_complaints(callback: CallbackQuery):
    async with db_pool.acquire() as conn:
        complaints = await conn.fetch("""
            SELECT c.reason, u1.username as from_uname, u2.username as target_uname, u2.photo_id as target_photo 
            FROM complaints c
            JOIN users u1 ON c.from_user_id = u1.user_id
            JOIN users u2 ON c.target_user_id = u2.user_id
            ORDER BY c.id DESC LIMIT 5
        """)

    if not complaints:
        await callback.message.answer("📭 Жалоб нет.")
        await callback.answer()
        return

    for comp in complaints:
        from_str = f"@{comp['from_uname']}" if comp['from_uname'] else "скрыт"
        target_str = f"@{comp['target_uname']}" if comp['target_uname'] else "скрыт"
        text = f"🚩 {from_str} подал жалобу на {target_str}\nПричина: {comp['reason']}"
        if comp['target_photo']:
            await callback.message.answer_photo(photo=comp['target_photo'], caption=text)
        else:
            await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data.in_(["top_week", "top_all", "my_ratings", "chat_target", "delete_profile"]))
async def stub_actions(callback: CallbackQuery):
    await callback.answer("Раздел в разработке!", show_alert=True)


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен с PostgreSQL!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
