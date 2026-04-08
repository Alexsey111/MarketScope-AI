from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Анализ карточки")],
            [KeyboardButton(text="📈 Анализ ниши")],
            [KeyboardButton(text="⚖ Сравнение площадок")]
        ],
        resize_keyboard=True
    )
    return keyboard