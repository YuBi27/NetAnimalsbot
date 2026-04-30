from aiogram.fsm.state import State, StatesGroup


class RequestStates(StatesGroup):
    choosing_category = State()
    waiting_location = State()
    waiting_description = State()
    waiting_media = State()
    waiting_contact = State()
    confirming = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_media = State()
    confirming = State()


class AdminCommentStates(StatesGroup):
    waiting_comment = State()  # request_id і new_status зберігаються в FSM data
    waiting_comment_media = State()  # очікуємо медіа до коментаря


class SelfSterilizationStates(StatesGroup):
    """FSM для заявки 'Я хочу стерилізувати самостійно'."""
    waiting_description = State()
    waiting_media = State()
    waiting_contact = State()
    confirming = State()


class FeedbackStates(StatesGroup):
    """FSM для фідбеку після стерилізації."""
    waiting_description = State()
    waiting_media = State()
    confirming = State()


class BiteReportStates(StatesGroup):
    waiting_date = State()
    waiting_location = State()
    waiting_animal_description = State()
    waiting_vaccinated = State()
    waiting_contact = State()
    confirming = State()


class LostAnimalBrowseStates(StatesGroup):
    browsing = State()
