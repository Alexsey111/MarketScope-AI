from aiogram.fsm.state import StatesGroup, State

class CardAnalysis(StatesGroup):
    waiting_for_text = State()

class NicheAnalysis(StatesGroup):
    waiting_for_description = State()

class PlatformCompare(StatesGroup):
    waiting_for_data = State()