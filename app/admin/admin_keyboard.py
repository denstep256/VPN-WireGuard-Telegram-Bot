from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)

from app.addons.button_text import BUTTON_TEXTS

# main_admin = ReplyKeyboardMarkup(
#     keyboard=[
#         [KeyboardButton(text=BUTTON_TEXTS["products"])],
#         [KeyboardButton(text=BUTTON_TEXTS["my_subs"])],
#         [KeyboardButton(text=BUTTON_TEXTS["how_connect"])],
#         [
#             KeyboardButton(text=BUTTON_TEXTS["help"]),
#             KeyboardButton(text=BUTTON_TEXTS["about"])
#         ],
#         [KeyboardButton(text=BUTTON_TEXTS["admin"])]
#     ],
#     resize_keyboard=True
# )


admin_panel = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=BUTTON_TEXTS["broadcast"]),
            KeyboardButton(text=BUTTON_TEXTS["statistics"])
        ],
        [
            KeyboardButton(text=BUTTON_TEXTS["add_server"]),
            KeyboardButton(text=BUTTON_TEXTS["manage_subs"])
        ],
        [KeyboardButton(text=BUTTON_TEXTS["ping_servers"])],
        [KeyboardButton(text=BUTTON_TEXTS["admin_back"])]
    ],
    resize_keyboard=True
)


stat_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=BUTTON_TEXTS["clients_on_server"]),
            KeyboardButton(text=BUTTON_TEXTS["users_in_bot"])
        ],
        [
            KeyboardButton(text=BUTTON_TEXTS["users_with_sub"]),
            KeyboardButton(text=BUTTON_TEXTS["users_with_trial"])
        ],
        [KeyboardButton(text=BUTTON_TEXTS["payments"])],
        [KeyboardButton(text=BUTTON_TEXTS["admin_back_short"])]
    ],
    resize_keyboard=True
)

send_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BUTTON_TEXTS["without_photo"])],
        [KeyboardButton(text=BUTTON_TEXTS["with_photo"])],
        [KeyboardButton(text=BUTTON_TEXTS["admin_back_short"])]
    ],
    resize_keyboard=True
)


preview_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(
        text=BUTTON_TEXTS["yes"],
        callback_data='confirm_broadcast'
    )],
    [InlineKeyboardButton(
        text=BUTTON_TEXTS["no"],
        callback_data='cancel_broadcast'
    )]
])