import asyncio
import logging
import sqlite3
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

# Токен твоего бота (вставь сюда или настрой через переменные окружения)
BOT_TOKEN = "8950068828:AAGGTOqKNHCGzLj-4VsfSjMe-ImLynRaNKg"

# Админы проекта (включая @BLRPMM, чей Telegram ID нужно узнать или указать числом)
ADMIN_USERNAMES = ["BLRPMM"]
ADMIN_IDS = [
    # Сюда можно вписать цифровой ID пользователя @BLRPMM для надежности
]

# Настройка базы данных SQLite
DB_NAME = "bot_database.db"


def init_db():
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            age INTEGER,
            gender TEXT,
            photo_id TEXT,
            status TEXT DEFAULT 'active',
            vip_days INTEGER DEFAULT 0,
            invited_by INTEGER
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER,
            to_user_id INTEGER,
            tier TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER,
            target_user_id INTEGER,
            reason TEXT
        )
    """)
  conn.commit()
  conn.close()


init_db()

router = Router()


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
          InlineKeyboardButton(
              text="📄 Моя анкета", callback_data="menu_profile"
          ),
      ],
      [
          InlineKeyboardButton(text="🏆 Топы", callback_data="menu_tops"),
          InlineKeyboardButton(text="💎 VIP", callback_data="menu_vip"),
      ],
      [
          InlineKeyboardButton(
              text="🔗 Реферальная программа", callback_data="menu_ref"
          )
      ],
  ]
  if user_id in ADMIN_IDS or (username and username in ADMIN_USERNAMES):
    kb.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
  return InlineKeyboardMarkup(inline_keyboard=kb)


def get_age_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="❌ Закончить регистрацию", callback_data="cancel_reg"
              )
          ]
      ]
  )


def get_gender_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(text="👨 Мужчина", callback_data="gender_male"),
              InlineKeyboardButton(
                  text="👩 Женщина", callback_data="gender_female"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="❌ Отмена", callback_data="cancel_reg"
              )
          ],
      ]
  )


def get_photo_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="❌ Закончить регистрацию", callback_data="cancel_reg"
              )
          ]
      ]
  )


def get_profile_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="⭐ ❤️ Меня оценили", callback_data="my_ratings"
              )
          ],
          [
              InlineKeyboardButton(
                  text="✏️ Изменить фото", callback_data="edit_photo"
              )
          ],
          [
              InlineKeyboardButton(
                  text="✏️ Изменить возраст", callback_data="edit_age"
              ),
              InlineKeyboardButton(
                  text="✏️ Изменить пол", callback_data="edit_gender"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="⭐ Кого оценивать", callback_data="menu_rate"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🌐 Язык / Language", callback_data="lang_settings"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🗑️ Удалить анкету", callback_data="delete_profile"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 Главное меню", callback_data="back_to_main"
              )
          ],
      ]
  )


def get_rating_tiers_kb(target_user_id: int):
  tiers = [
      "Bad3",
      "Bad5",
      "Ltb",
      "Mtb",
      "Htb",
      "Stacy Lite",
      "Stacy",
      "True Eve",
  ]
  buttons = []
  row = []
  for tier in tiers:
    row.append(
        InlineKeyboardButton(
            text=f"🌸 {tier}", callback_data=f"rate_{target_user_id}_{tier}"
        )
    )
    if len(row) == 2:
      buttons.append(row)
      row = []
  if row:
    buttons.append(row)

  buttons.append(
      [InlineKeyboardButton(text="💬 Хочу пообщаться", callback_data="chat_target")]
  )
  buttons.append(
      [
          InlineKeyboardButton(
              text="🚩 Жалоба", callback_data=f"complaint_{target_user_id}"
          )
      ]
  )
  return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_panel_kb():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📊 Статистика", callback_data="admin_stats"
              )
          ],
          [
              InlineKeyboardButton(
                  text="💎 Выдать VIP", callback_data="admin_give_vip"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🚩 Жалобы", callback_data="admin_complaints"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 Главное меню", callback_data="back_to_main"
              )
          ],
      ]
  )


# --- Хэндлеры ---


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
  user_id = message.from_user.id
  username = message.from_user.username
  args = message.text.split()

  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT name, status FROM users WHERE user_id = ?", (user_id,)
  )
  user = cursor.fetchone()

  if not user and len(args) > 1 and args[1].startswith("ref_"):
    try:
      referrer_id = int(args[1].split("_")[1])
      if referrer_id != user_id:
        cursor.execute(
            "UPDATE users SET vip_days = vip_days + 1 WHERE user_id = ?",
            (referrer_id,),
        )
        conn.commit()
    except ValueError:
      pass

  if user and user[1] == "active":
    conn.close()
    await message.answer(
        "👋 Главное меню\nВыбирай раздел — здесь начинается самое интересное.",
        reply_markup=get_main_menu_kb(user_id, username),
    )
    return

  conn.close()

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="📄 Политика конфиденциальности",
                  url="https://telegram.org",
              )
          ],
          [
              InlineKeyboardButton(
                  text="📄 Условия использования", url="https://telegram.org"
              )
          ],
          [
              InlineKeyboardButton(
                  text="✅ Мне 14+, принимаю", callback_data="accept_rules"
              )
          ],
          [
              InlineKeyboardButton(
                  text="❌ Отмена", callback_data="cancel_reg"
              )
          ],
      ]
  )
  await message.answer(
      "🔒 **Подтверждение возраста и правил**\n\nПродолжая, ты подтверждаешь, что тебе уже исполнилось **14 лет**, и принимаешься Политику конфиденциальности и Условия использования.\n\nОткрой документы по кнопкам ниже и нажми «Мне 14+, принимаю».",
      reply_markup=kb,
      parse_mode="Markdown",
  )


@router.callback_query(F.data == "accept_rules")
async def accept_rules(callback: CallbackQuery, state: FSMContext):
  await callback.message.edit_text(
      "🎂 **Сколько тебе лет?**\n\nНапиши возраст одним числом от **14** до **99**.",
      reply_markup=get_age_kb(),
      parse_mode="Markdown",
  )
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
  await message.answer(
      "✨ **Выбери свой пол**\n\nЭти данные будут отображаться в анкете.",
      reply_markup=get_gender_kb(),
      parse_mode="Markdown",
  )
  await state.set_state(RegStates.gender)


@router.callback_query(RegStates.gender, F.data.startswith("gender_"))
async def process_gender(callback: CallbackQuery, state: FSMContext):
  gender = "мужчина" if callback.data == "gender_male" else "женщина"
  await state.update_data(gender=gender)
  await callback.message.edit_text(
      "📸 **Добавь главное фото**\n\nНа фотографии должно быть видно твоё лицо.\n\nИспользуй свою настоящую фотографию. За чужие, фейковые или созданные ИИ изображения анкета может быть удалена.",
      reply_markup=get_photo_kb(),
      parse_mode="Markdown",
  )
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

  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      """
        INSERT OR REPLACE INTO users (user_id, username, name, age, gender, photo_id, status)
        VALUES (?, ?, ?, ?, ?, ?, 'active')
    """,
      (user_id, username, name, age, gender, photo_id),
  )
  conn.commit()
  conn.close()

  await state.clear()
  await message.answer(
      f"👤 Готово, {name}! Регистрация завершена.\n\nОценивай анкеты, получай собственный тир, попадай в недельный топ и приглашай друзей за бесплатный VIP."
  )
  await message.answer(
      "⭐ Главное меню\nВыбирай раздел — здесь начинается самое интересное.",
      reply_markup=get_main_menu_kb(user_id, message.from_user.username),
  )


@router.callback_query(F.data == "cancel_reg")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  await callback.message.edit_text(
      "❌ Регистрация не пройдена.\n\nНапиши /start, чтобы начать заново."
  )
  await callback.answer()


@router.callback_query(F.data == "menu_profile")
async def show_profile(callback: CallbackQuery):
  user_id = callback.from_user.id
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT name, age, gender, photo_id, vip_days FROM users WHERE user_id = ?",
      (user_id,),
  )
  user = cursor.fetchone()
  conn.close()

  if not user:
    await callback.message.answer("Анкета не найдена. Нажми /start")
    await callback.answer()
    return

  name, age, gender, photo_id, vip_days = user
  vip_text = f"активен (дней: {vip_days})" if vip_days > 0 else "не активен"
  caption = (
      f"📄 **{name}**\nВозраст: {age}\nПол: {gender}\nVIP: {vip_text}\n\n🕸️"
      f" Статистика\nТвой тир: пока формируется\nПолучено оценок: 0"
  )

  await callback.message.answer_photo(
      photo=photo_id,
      caption=caption,
      reply_markup=get_profile_kb(),
      parse_mode="Markdown",
  )
  await callback.answer()


@router.callback_query(F.data == "menu_rate")
async def start_rating(callback: CallbackQuery):
  user_id = callback.from_user.id
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT user_id, name, age, photo_id FROM users WHERE user_id != ? AND status = 'active' ORDER"
      " BY RANDOM() LIMIT 1",
      (user_id,),
  )
  target = cursor.fetchone()
  conn.close()

  if not target:
    await callback.message.answer(
        "😔 Пока нет доступных анкет для оценки. Загляни позже!"
    )
    await callback.answer()
    return

  t_id, t_name, t_age, t_photo = target
  caption = (
      f"🌸 **{t_name}, {t_age}** · Средний тир: пока формируется\n👥 Анкету"
      f" оценили: 0\n\nКакой тир поставишь?"
  )

  await callback.message.answer_photo(
      photo=t_photo,
      caption=caption,
      reply_markup=get_rating_tiers_kb(t_id),
      parse_mode="Markdown",
  )
  await callback.answer()


@router.callback_query(F.data.startswith("rate_"))
async def process_tier_rating(callback: CallbackQuery):
  data_parts = callback.data.split("_")
  target_user_id = int(data_parts[1])
  tier = data_parts[2]
  from_user_id = callback.from_user.id

  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO ratings (from_user_id, to_user_id, tier) VALUES (?, ?, ?)",
      (from_user_id, target_user_id, tier),
  )
  conn.commit()
  conn.close()

  await callback.answer(f"Ты поставил тир: {tier}!")
  await start_rating(callback)


@router.callback_query(F.data.startswith("complaint_"))
async def process_complaint_prompt(callback: CallbackQuery):
  target_user_id = int(callback.data.split("_")[1])
  from_user_id = callback.from_user.id

  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO complaints (from_user_id, target_user_id, reason) VALUES (?, ?, ?)",
      (from_user_id, target_user_id, "Нарушение правил / Спам"),
  )
  conn.commit()
  conn.close()

  await callback.answer("🚨 Жалоба успешно отправлена администрации!", show_alert=True)
  await start_rating(callback)


@router.callback_query(F.data == "menu_tops")
async def show_tops(callback: CallbackQuery):
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🏆 Топ недели", callback_data="top_week")],
          [InlineKeyboardButton(text="👑 Общий топ", callback_data="top_all")],
          [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
      ]
  )
  await callback.message.answer(
      "📊 **Топы**\n\nВыбери рейтинг. В топах учитываются оценки твоей текущей анкеты.",
      reply_markup=kb,
      parse_mode="Markdown",
  )
  await callback.answer()


@router.callback_query(F.data == "menu_vip")
async def show_vip(callback: CallbackQuery):
  text = (
      "💎 **VIP Статус**\n\nБольше показов. Больше оценок. Больше внимания.\n\n"
      "⭐ 1 день — 10 Stars\n⭐ 7 дней — 49 Stars\n⭐ 30 дней — 99 Stars\n🥂 Навсегда — 249 Stars"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="⭐ Купить 1 день (10 Stars)", callback_data="buy_vip_1"
              )
          ],
          [
              InlineKeyboardButton(
                  text="🔙 Главное меню", callback_data="back_to_main"
              )
          ],
      ]
  )
  await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()


@router.callback_query(F.data == "menu_ref")
async def show_referral(callback: CallbackQuery):
  bot_info = await callback.bot.get_me()
  user_id = callback.from_user.id
  ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

  text = (
      f"🔗 **Получи VIP бесплатно**\n\nПриглаши друга по персональной ссылке. Когда он завершит регистрацию, ты автоматически получишь **1 день VIP**.\n\n"
      f"Твоя ссылка:\n`{ref_link}`"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🔙 Главное меню", callback_data="back_to_main"
              )
          ]
      ]
  )
  await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
  await callback.message.answer(
      "⭐ Главное меню\nВыбирай раздел — здесь начинается самое интересное.",
      reply_markup=get_main_menu_kb(
          callback.from_user.id, callback.from_user.username
      ),
  )
  await callback.answer()


# --- Админ-панель ---


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
  user_id = callback.from_user.id
  username = callback.from_user.username
  if user_id not in ADMIN_IDS and (not username or username not in ADMIN_USERNAMES):
    await callback.answer("У тебя нет доступа к этой панели.", show_alert=True)
    return

  await callback.message.answer(
      "👑 **Панель администратора**\n\nВыбери нужный раздел:",
      reply_markup=get_admin_panel_kb(),
      parse_mode="Markdown",
  )
  await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()

  cursor.execute("SELECT COUNT(*) FROM users")
  total_users = cursor.fetchone()[0]

  cursor.execute("SELECT COUNT(*) FROM ratings")
  total_ratings = cursor.fetchone()[0]

  cursor.execute("SELECT COUNT(*) FROM complaints")
  total_complaints = cursor.fetchone()[0]

  conn.close()

  text = (
      f"📊 **Полная статистика бота**\n\n"
      f"👤 Всего создано анкет (пользователей): **{total_users}**\n"
      f"⭐ Всего поставлено оценок: **{total_ratings}**\n"
      f"🚩 Всего подано жалоб: **{total_complaints}**"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🔙 В админ-панель", callback_data="admin_panel"
              )
          ]
      ]
  )
  await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
  await callback.answer()


@router.callback_query(F.data == "admin_give_vip")
async def admin_give_vip_start(callback: CallbackQuery, state: FSMContext):
  await callback.message.answer(
      "💎 Введи юзернейм пользователя (например, `@username`), которому хочешь выдать VIP:"
  )
  await state.set_state(AdminVipStates.username)
  await callback.answer()


@router.message(AdminVipStates.username)
async def admin_vip_get_username(message: Message, state: FSMContext):
  target_username = message.text.strip().lstrip("@")
  await state.update_data(target_username=target_username)
  await message.answer("🔢 Теперь введи количество дней VIP (целым числом):")
  await state.set_state(AdminVipStates.days)


@router.message(AdminVipStates.days)
async def admin_vip_get_days(message: Message, state: FSMContext):
  if not message.text.isdigit():
    await message.answer("⚠️ Пожалуйста, введи количество дней числом.")
    return

  days = int(message.text)
  data = await state.get_data()
  target_username = data.get("target_username")

  conn = sqlite3.connect(DB_NAME)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT user_id FROM users WHERE username = ?", (target_username,)
  )
  user = cursor.fetchone()

  if not user:
    conn.close()
    await message.answer(
        f"❌ Пользователь @{target_username} не найден в базе данных бота."
    )
    await state.clear()
    return

  target_user_id = user[0]
  cursor.execute(
      "UPDATE users SET vip_days = vip_days + ? WHERE user_id = ?",
      (days, target_user_id),
  )
  conn.commit()
  conn.close()

  await state.clear()
  await message.answer(
      
