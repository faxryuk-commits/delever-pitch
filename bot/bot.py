import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
DATAROOM_URL = os.getenv(
    "DATAROOM_URL",
    "https://faxryuk-commits.github.io/delever-pitch/dataroom.html",
)
DB_PATH = Path(__file__).parent / "db.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

router = Router()


def load_db() -> dict:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return {"tokens": {}, "requests": {}, "admin_id": ADMIN_CHAT_ID}


def save_db(db: dict):
    DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False))


def generate_token(user_id: int) -> str:
    raw = f"{user_id}-{time.time()}-delever-vdr"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class RequestForm(StatesGroup):
    name = State()
    company = State()
    email = State()
    purpose = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    db = load_db()

    if not db.get("admin_id") and ADMIN_CHAT_ID:
        db["admin_id"] = ADMIN_CHAT_ID
        save_db(db)

    user_id = str(message.from_user.id)
    if user_id in db.get("tokens", {}):
        token = db["tokens"][user_id]["token"]
        url = f"{DATAROOM_URL}?token={token}"
        await message.answer(
            f"✅ <b>У вас уже есть доступ к Data Room</b>\n\n"
            f"🔗 <a href='{url}'>Открыть Delever Data Room</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if user_id in db.get("requests", {}):
        status = db["requests"][user_id].get("status", "pending")
        if status == "pending":
            await message.answer(
                "⏳ <b>Ваш запрос уже отправлен</b>\n\n"
                "Мы рассмотрим его в ближайшее время и вышлем ссылку.",
                parse_mode=ParseMode.HTML,
            )
            return

    await message.answer(
        "🔒 <b>Delever Virtual Data Room</b>\n\n"
        "Добро пожаловать! Для получения доступа к дата-руму заполните краткую анкету.\n\n"
        "📝 <b>Введите ваше полное имя:</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestForm.name)


@router.message(RequestForm.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        "🏢 <b>Название компании / фонда:</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestForm.company)


@router.message(RequestForm.company)
async def process_company(message: Message, state: FSMContext):
    await state.update_data(company=message.text)
    await message.answer(
        "📧 <b>Ваш email:</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestForm.email)


@router.message(RequestForm.email)
async def process_email(message: Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer(
        "🎯 <b>Цель запроса:</b>\n"
        "Например: due diligence, инвестиции, партнёрство",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(RequestForm.purpose)


@router.message(RequestForm.purpose)
async def process_purpose(message: Message, state: FSMContext):
    data = await state.get_data()
    data["purpose"] = message.text
    await state.clear()

    db = load_db()
    user_id = str(message.from_user.id)
    username = message.from_user.username or "—"

    db.setdefault("requests", {})[user_id] = {
        "name": data["name"],
        "company": data["company"],
        "email": data["email"],
        "purpose": data["purpose"],
        "username": username,
        "status": "pending",
        "timestamp": int(time.time()),
    }
    save_db(db)

    await message.answer(
        "✅ <b>Спасибо! Ваша заявка отправлена.</b>\n\n"
        "Мы рассмотрим её и отправим ссылку на Data Room в этот чат.",
        parse_mode=ParseMode.HTML,
    )

    admin_id = db.get("admin_id")
    if admin_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Одобрить",
                        callback_data=f"approve:{user_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"reject:{user_id}",
                    ),
                ]
            ]
        )
        await message.bot.send_message(
            chat_id=int(admin_id),
            text=(
                "📩 <b>Новый запрос на Data Room</b>\n\n"
                f"👤 <b>Имя:</b> {data['name']}\n"
                f"🏢 <b>Компания:</b> {data['company']}\n"
                f"📧 <b>Email:</b> {data['email']}\n"
                f"🎯 <b>Цель:</b> {data['purpose']}\n"
                f"💬 <b>Telegram:</b> @{username}\n"
                f"🆔 <b>ID:</b> {user_id}"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("approve:"))
async def approve_request(callback: CallbackQuery):
    user_id = callback.data.split(":")[1]
    db = load_db()

    if user_id not in db.get("requests", {}):
        await callback.answer("Запрос не найден", show_alert=True)
        return

    token = generate_token(int(user_id))
    req = db["requests"][user_id]
    req["status"] = "approved"
    db.setdefault("tokens", {})[user_id] = {
        "token": token,
        "name": req["name"],
        "company": req["company"],
        "email": req["email"],
        "approved_at": int(time.time()),
    }
    save_db(db)

    url = f"{DATAROOM_URL}?token={token}"
    await callback.bot.send_message(
        chat_id=int(user_id),
        text=(
            "🎉 <b>Доступ одобрен!</b>\n\n"
            f"🔗 <a href='{url}'>Открыть Delever Data Room</a>\n\n"
            "Ссылка персональная и действует 30 дней."
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>ОДОБРЕНО</b> · Токен: <code>{token[:12]}…</code>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("Доступ выдан ✅")


@router.callback_query(F.data.startswith("reject:"))
async def reject_request(callback: CallbackQuery):
    user_id = callback.data.split(":")[1]
    db = load_db()

    if user_id in db.get("requests", {}):
        db["requests"][user_id]["status"] = "rejected"
        save_db(db)

    await callback.bot.send_message(
        chat_id=int(user_id),
        text=(
            "К сожалению, ваш запрос на доступ к Data Room отклонён.\n\n"
            "Если вы считаете что это ошибка, свяжитесь с нами: invest@delever.uz"
        ),
    )

    await callback.message.edit_text(
        callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("Запрос отклонён")


@router.message(F.text == "/admin")
async def cmd_admin(message: Message):
    db = load_db()
    if not db.get("admin_id"):
        db["admin_id"] = str(message.from_user.id)
        save_db(db)
        await message.answer(
            f"✅ Вы назначены администратором.\nВаш Chat ID: <code>{message.from_user.id}</code>",
            parse_mode=ParseMode.HTML,
        )
    elif str(message.from_user.id) == str(db["admin_id"]):
        tokens = db.get("tokens", {})
        requests = db.get("requests", {})
        pending = sum(1 for r in requests.values() if r.get("status") == "pending")
        await message.answer(
            f"📊 <b>Статистика Data Room</b>\n\n"
            f"✅ Выдано доступов: {len(tokens)}\n"
            f"⏳ Ожидают одобрения: {pending}\n"
            f"📝 Всего запросов: {len(requests)}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer("⛔ У вас нет прав администратора.")


@router.message(F.text == "/tokens")
async def cmd_tokens(message: Message):
    db = load_db()
    if str(message.from_user.id) != str(db.get("admin_id")):
        return

    tokens = db.get("tokens", {})
    if not tokens:
        await message.answer("Нет выданных токенов.")
        return

    text = "🔑 <b>Выданные доступы:</b>\n\n"
    for uid, info in tokens.items():
        text += (
            f"• <b>{info['name']}</b> ({info['company']})\n"
            f"  📧 {info['email']} · 🔑 <code>{info['token'][:12]}…</code>\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)


async def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set!")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Delever Data Room Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
