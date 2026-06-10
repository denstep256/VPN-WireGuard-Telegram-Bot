from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)
from sqlalchemy import select

from sqlalchemy.orm import Session

from app.addons.button_text import BUTTON_TEXTS
from app.database.models import Server, Subscribers
from app.vpn.provisioning import PROTOCOL_WIREGUARD, PROTOCOL_XUI, get_protocol_label, get_record_protocol
from config import ADMIN_ID


def get_subscriptions_kb(subs: list[Subscribers]) -> InlineKeyboardMarkup:
    buttons = []
    for sub in subs:
        # Например: "Amsterdam №1 — до 2025-08-15"
        protocol_label = get_protocol_label(get_record_protocol(sub))
        text = f"{protocol_label}: {sub.server_region} №{sub.server_region_id} — до {sub.expiry_date}"
        callback_data = f"renew_sub|{sub.id}"  # используем ID записи
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_protocols_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="WireGuard", callback_data=f"proto|{PROTOCOL_WIREGUARD}")],
        [InlineKeyboardButton(text="3xUI", callback_data=f"proto|{PROTOCOL_XUI}")],
    ])


async def get_servers_keyboard(session: Session, protocol: str = PROTOCOL_WIREGUARD) -> InlineKeyboardMarkup:
    # Получаем активные серверы из БД
    result = await session.execute(
        select(Server).where(Server.is_active == True).order_by(Server.region)
    )
    servers = result.scalars().all()

    # Формируем кнопки
    buttons = []
    for server in servers:
        button_text = f"{server.region} №{server.region_id}"
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f'srv|{protocol}|{server.region}|{server.region_id}'
            )
        ])
    # Если серверов нет — показываем уведомление
    if not buttons:
        buttons.append([
            InlineKeyboardButton(
                text="⚠️ Нет доступных серверов",
                callback_data='no_servers'
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_buy_kb(region: str, region_id: int, protocol: str = PROTOCOL_WIREGUARD) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_1"], callback_data=f'one_month|{protocol}|{region}|{region_id}')],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_6"], callback_data=f'six_month|{protocol}|{region}|{region_id}')],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_12"], callback_data=f'twelve_month|{protocol}|{region}|{region_id}')],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_test"], callback_data=f'test_3_days|{protocol}|{region}|{region_id}')],
    ])

def get_renew_buy_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_TEXTS["renew_1"], callback_data=f"renew_pay|{sub_id}|monthly_subs")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["renew_6"], callback_data=f"renew_pay|{sub_id}|semi_annual_subs")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["renew_12"], callback_data=f"renew_pay|{sub_id}|annual_subs")],
    ])


# main = ReplyKeyboardMarkup(
#     keyboard=[
#         [KeyboardButton(text=BUTTON_TEXTS["products"])],
#         [KeyboardButton(text=BUTTON_TEXTS["my_subs"])],
#         [KeyboardButton(text=BUTTON_TEXTS["how_connect"])],
# [
#             KeyboardButton(text=BUTTON_TEXTS["promocode"]),
#             KeyboardButton(text=BUTTON_TEXTS["invite_friend"])
#         ],
#         [
#             KeyboardButton(text=BUTTON_TEXTS["help"]),
#             KeyboardButton(text=BUTTON_TEXTS["about"])
#         ]
#     ],
#     resize_keyboard=True
# )


help_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=BUTTON_TEXTS["write"],
                          url="https://t.me/ZenithVPN_support",
                          callback_data='help_button')]])

how_to_connect_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BUTTON_TEXTS["iphone"])],
                                                  [KeyboardButton(text=BUTTON_TEXTS["android"])],
                                                  [KeyboardButton(text=BUTTON_TEXTS["back"])]],
                             resize_keyboard=True)

accept_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BUTTON_TEXTS["downloaded"])],
                                          [KeyboardButton(text=BUTTON_TEXTS["back"])]],
                                resize_keyboard=True)

back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BUTTON_TEXTS["back"])]], resize_keyboard=True)

iphone_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=BUTTON_TEXTS["download"],
                          url="https://apps.apple.com/ru/app/wireguard/id1441195209",
                          callback_data='iph_kb')]])

android_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=BUTTON_TEXTS["download"],
                          url="https://play.google.com/store/apps/details?id=com.wireguard.android&pcampaignid=web_share",
                          callback_data='and_kb')]])

download_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=BUTTON_TEXTS["instruction_iphone"],
                          url="https://teletype.in/@zenithvpn/ogi7tHwL4qV")],
    [InlineKeyboardButton(text=BUTTON_TEXTS["instruction_android"],
                          url='https://teletype.in/@zenithvpn/N1lyKcbCMeV')],
    [InlineKeyboardButton(text=BUTTON_TEXTS["check_vpn"],
                          url='https://2ip.ru')]
])

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=BUTTON_TEXTS["products"])],
        [KeyboardButton(text=BUTTON_TEXTS["my_subs"])],
        [KeyboardButton(text=BUTTON_TEXTS["how_connect"])],
        [
            KeyboardButton(text=BUTTON_TEXTS["promocode"]),
            KeyboardButton(text=BUTTON_TEXTS["invite_friend"]),
        ],
        [
            KeyboardButton(text=BUTTON_TEXTS["help"]),
            KeyboardButton(text=BUTTON_TEXTS["about"]),
        ],
    ]

    if user_id == int(ADMIN_ID):
        keyboard.append([KeyboardButton(text=BUTTON_TEXTS["admin"])])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )
