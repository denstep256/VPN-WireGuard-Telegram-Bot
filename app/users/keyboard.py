from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)
from app.addons.button_text import BUTTON_TEXTS
from config import ADMIN_ID


def get_buy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_1"], callback_data="one_month")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_6"], callback_data="six_month")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_12"], callback_data="twelve_month")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["buy_test"], callback_data="test_3_days")],
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

back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BUTTON_TEXTS["back"])]], resize_keyboard=True)


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
