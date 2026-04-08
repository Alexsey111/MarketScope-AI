import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.keyboards import main_menu
from bot.states import CardAnalysis
from services.llm_service import analyze_card
from services.scoring import calculate_score, format_score_block
from services.database import save_history

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "MarketScope AI\n\nВыберите сценарий:",
        reply_markup=main_menu()
    )

@router.message(F.text == "📊 Анализ карточки")
async def start_card(message: Message, state: FSMContext):
    await state.set_state(CardAnalysis.waiting_for_text)
    await message.answer("Отправьте текст карточки товара для анализа.")

@router.message(CardAnalysis.waiting_for_text)
async def process_card(message: Message, state: FSMContext):
    user_text = message.text

    await message.answer("⏳ Выполняю анализ...")

    analysis = await analyze_card(user_text)

    # scoring
    score_data = calculate_score(user_text)
    score_block = format_score_block(score_data)

    final_response = f"{analysis}\n\n{score_block}"

    await message.answer(final_response)

    # Сохранение в историю
    await asyncio.to_thread(
        save_history,
        message.from_user.id,
        user_text,
        score_data["total_score"],
    )

    await state.clear()
