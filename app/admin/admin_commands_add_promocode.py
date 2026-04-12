import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from datetime import datetime, time

import app.admin.admin_keyboard as admin_kb
from app.addons.button_text import BUTTON_TEXTS
from app.database.models import PromoCode, async_session
from config import ADMIN_ID


admin_add_promo_router = Router()
logger = logging.getLogger(__name__)


class AddPromoState(StatesGroup):
    waiting_code = State()
    waiting_discount = State()
    waiting_first_purchase_only = State()
    waiting_max_uses = State()
    waiting_owner = State()
    waiting_expiry_date = State()


def _is_admin(user_id: int) -> bool:
    return user_id == int(ADMIN_ID)


def _parse_expiry_input(raw_text: str | None) -> datetime | None:
    text = (raw_text or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(text, fmt).date()
            return datetime.combine(parsed_date, time(hour=23, minute=59, second=59))
        except ValueError:
            continue
    return None


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"


@admin_add_promo_router.message(F.text == BUTTON_TEXTS["add_promocode"])
async def start_add_promo(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    await state.clear()
    await state.set_state(AddPromoState.waiting_code)
    await message.answer(
        "Введите код промокода (латиница/цифры, до 32 символов).\nПример: <code>ZENITH10</code>",
        parse_mode="HTML",
    )


@admin_add_promo_router.message(AddPromoState.waiting_code)
async def add_promo_code(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        await message.answer("У вас нет доступа")
        return

    code = (message.text or "").strip().upper()
    if not code or len(code) > 32 or not all(ch.isalnum() or ch in "-_" for ch in code):
        await message.answer("❌ Некорректный код. Разрешены A-Z, 0-9, '-', '_' и длина до 32.")
        return

    async with async_session() as session:
        exists = await session.execute(select(PromoCode.id).where(PromoCode.code == code))
        if exists.scalar_one_or_none() is not None:
            await message.answer("❌ Такой промокод уже существует.")
            return

    await state.update_data(code=code)
    await state.set_state(AddPromoState.waiting_discount)
    await message.answer("Укажите размер скидки в процентах (1-90):")


@admin_add_promo_router.message(AddPromoState.waiting_discount)
async def add_promo_discount(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Укажите целое число от 1 до 90.")
        return

    discount = int(text)
    if not 1 <= discount <= 90:
        await message.answer("❌ Скидка должна быть в диапазоне 1-90.")
        return

    await state.update_data(discount_percent=discount)
    await state.set_state(AddPromoState.waiting_first_purchase_only)
    await message.answer("Промокод только на первую оплату? Ответьте: да / нет")


@admin_add_promo_router.message(AddPromoState.waiting_first_purchase_only)
async def add_promo_first_purchase_only(message: Message, state: FSMContext):
    answer = (message.text or "").strip().lower()
    if answer not in {"да", "нет"}:
        await message.answer("❌ Ответьте: да или нет.")
        return

    await state.update_data(first_purchase_only=(answer == "да"))
    await state.set_state(AddPromoState.waiting_max_uses)
    await message.answer("Сколько раз один пользователь может применить код? (1-20)")


@admin_add_promo_router.message(AddPromoState.waiting_max_uses)
async def add_promo_max_uses(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Укажите целое число от 1 до 20.")
        return

    max_uses = int(text)
    if not 1 <= max_uses <= 20:
        await message.answer("❌ Значение должно быть в диапазоне 1-20.")
        return

    await state.update_data(max_uses_per_user=max_uses)
    await state.set_state(AddPromoState.waiting_owner)
    await message.answer(
        "Введите TG ID владельца для персонального промокода.\n"
        "Если код общий — отправьте <code>0</code>.",
        parse_mode="HTML",
    )


@admin_add_promo_router.message(AddPromoState.waiting_owner)
async def add_promo_owner(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Введите число (TG ID) или 0.")
        return

    owner_id_raw = int(text)
    owner_tg_id = None if owner_id_raw == 0 else owner_id_raw

    await state.update_data(owner_tg_id=owner_tg_id)
    await state.set_state(AddPromoState.waiting_expiry_date)
    await message.answer(
        "Введите дату окончания промокода.\n"
        "Формат: <code>ДД.ММ.ГГГГ</code> или <code>YYYY-MM-DD</code>.\n"
        "Промокод не может быть бессрочным.",
        parse_mode="HTML",
    )


@admin_add_promo_router.message(AddPromoState.waiting_expiry_date)
async def add_promo_expiry_date(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        await message.answer("У вас нет доступа")
        return

    expires_at = _parse_expiry_input(message.text)
    if not expires_at:
        await message.answer(
            "❌ Некорректная дата. Используйте формат <code>ДД.ММ.ГГГГ</code> или <code>YYYY-MM-DD</code>.",
            parse_mode="HTML",
        )
        return

    if expires_at <= datetime.utcnow():
        await message.answer("❌ Дата окончания должна быть позже текущего момента.")
        return

    data = await state.get_data()
    owner_tg_id = data.get("owner_tg_id")
    try:
        async with async_session() as session:
            promo = PromoCode(
                code=data["code"],
                discount_percent=data["discount_percent"],
                owner_tg_id=owner_tg_id,
                is_active=True,
                first_purchase_only=data["first_purchase_only"],
                max_uses_per_user=data["max_uses_per_user"],
                expires_at=expires_at,
            )
            session.add(promo)
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка создания промокода: admin=%s code=%s owner_tg_id=%s",
            _admin_actor(message.from_user),
            data.get("code"),
            owner_tg_id,
        )
        await message.answer("❌ Не удалось создать промокод из-за внутренней ошибки.")
        return

    await state.clear()
    logger.info(
        "Админ %s создал промокод: code=%s discount=%s%% first_purchase_only=%s max_uses_per_user=%s owner_tg_id=%s expires_at=%s",
        _admin_actor(message.from_user),
        data["code"],
        data["discount_percent"],
        data["first_purchase_only"],
        data["max_uses_per_user"],
        owner_tg_id,
        expires_at.isoformat(),
    )
    await message.answer(
        "✅ Промокод создан.\n"
        f"Код: <code>{data['code']}</code>\n"
        f"Скидка: <b>{data['discount_percent']}%</b>\n"
        f"Только первая оплата: <b>{'да' if data['first_purchase_only'] else 'нет'}</b>\n"
        f"Лимит на пользователя: <b>{data['max_uses_per_user']}</b>\n"
        f"Персональный: <b>{'да' if owner_tg_id else 'нет'}</b>\n"
        f"Действует до: <b>{expires_at.date().isoformat()}</b>",
        parse_mode="HTML",
        reply_markup=admin_kb.admin_panel,
    )
