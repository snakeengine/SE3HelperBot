# states.py
from aiogram.dispatcher.filters.state import State, StatesGroup

class SupplierApply(StatesGroup):
    FULL_NAME = State()
    COUNTRY_CITY = State()
    CONTACT = State()
    ANDROID_EXP = State()
    PORTFOLIO = State()
    CONFIRM = State()

class AdminAsk(StatesGroup):
    WAITING_QUESTION = State()
