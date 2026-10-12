from aiogram.fsm.state import State, StatesGroup


class CreateShop(StatesGroup):
    token = State()
    admin_id = State()
    name = State()


class ChangeAdmin(StatesGroup):
    admin_id = State()
