import asyncio
import logging
import asyncpg
import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, InputMediaPhoto

# --- CONFIG ---
BOT_TOKEN = "ТВОЙ_ТОКЕН"
DATABASE_URL = "postgresql://neondb_owner:npg_dynKuOEmo28X@ep-young-haze-axtbbubu-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require"
ADMINS = ["BLRPMM", "Lelouch_Vi_Britannia"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

router = Router()
db_pool = None

# --- STATES ---
class RegState(StatesGroup):
    age = State()
    gender = State()
    photo = State()

class AdminState(StatesGroup):
    target_user = State()
    vip_amount = State()

# --- DATABASE ---
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, username TEXT, name TEXT, 
                age INT, gender TEXT, photo_id TEXT, vip_days INT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY, from_id BIGINT, to_id BIGINT, tier TEXT
            );
            CREATE TABLE IF NOT EXISTS complaints (
                id SERIAL PRIMARY KEY, from_id BIGINT, target_id BIGINT, reason TEXT
            );
        """)

# --- KEYBOARDS ---
def get_main_menu(username):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ ОЦЕНИТЬ АНКЕТЫ", callback_data="rate_menu")],
        [InlineKeyboardButton(text="📄 ПРОФИЛЬ", callback_data="profile"), 
         InlineKeyboardButton(text="💎 VIP", callback_data="vip_menu")],
        [InlineKeyboardButton(text="🏆 ТОПЫ", callback_data="tops"), 
         InlineKeyboardButton(text="🔗 РЕФЕРАЛ", callback_data="ref_menu")],
    ])
    if username in ADMINS:
        kb.inline_keyboard.append([InlineKeyboardButton(text="👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
    return kb

def get_rating_kb(target_id):
    tiers = ["Sub 3", "Sub 5", "Ltb", "Mtb", "Htb", "Stacy Lite", "Stacy", "True Eve/Adam"]
    buttons = [[InlineKeyboardButton(text=t, callback_data=f"vote_{target_id}_{t}")] for t in tiers]
    buttons.append([InlineKeyboardButton(text="💬 Общение", callback_data="chat_req"), 
                    InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{target_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- HANDLERS ---
@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    # Логика рефералки
    args = msg.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = int(args[1].split("_")[1])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET vip_days = vip_days + 1 WHERE user_id = $1", ref_id)
    
    await msg.answer("👋 **Добро пожаловать в систему!**\nДля начала работы пройди регистрацию.")
    await msg.answer("🎂 Введи свой возраст (12-30):")
    await state.set_state(RegState.age)

@router.message(RegState.age)
async def proc_age(msg: Message, state: FSMContext):
    await state.update_data(age=int(msg.text))
    await msg.answer("🚻 Выбери пол:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужчина ♂️", callback_data="gender_male"), 
         InlineKeyboardButton(text="Женщина ♀️", callback_data="gender_female")]
    ]))
    await state.set_state(RegState.gender)

@router.callback_query(F.data.startswith("gender_"))
async def proc_gender(call: CallbackQuery, state: FSMContext):
    await state.update_data(gender=call.data.split("_")[1])
    await call.message.edit_text("📸 Отправь фото для анкеты:")
    await state.set_state(RegState.photo)

@router.message(RegState.photo, F.photo)
async def proc_photo(msg: Message, state: FSMContext):
    data = await state.get_data()
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username, age, gender, photo_id) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id) DO UPDATE SET age=$3, gender=$4, photo_id=$5", 
                           msg.from_user.id, msg.from_user.username, data['age'], data['gender'], msg.photo[-1].file_id)
    await msg.answer("✅ Профиль активирован!", reply_markup=get_main_menu(msg.from_user.username))
    await state.clear()

@router.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.username not in ADMINS: return
    await call.message.edit_text("👑 **АДМИН-ПАНЕЛЬ**\n\nУправляй системой эффективно.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🚩 Жалобы", callback_data="admin_complaints")],
        [InlineKeyboardButton(text="💎 Выдать VIP", callback_data="admin_vip")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ]))

@router.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    async with db_pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        rates = await conn.fetchval("SELECT COUNT(*) FROM ratings")
    await call.message.edit_text(f"📊 **СТАТИСТИКА**\n\n👤 Пользователей: {users}\n⭐ Оценок: {rates}\n🕒 Время: {datetime.datetime.now().strftime('%H:%M')}", 
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]]))

# --- MAIN ---
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
