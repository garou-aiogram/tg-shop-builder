from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.builder.handlers import router
from app.security.crypto import TokenCipher
from app.services.shops import ShopService


def build_builder_dispatcher(*, shop_service: ShopService, cipher: TokenCipher) -> Dispatcher:
    # MemoryStorage: состояние FSM теряется при рестарте процесса — для MVP приемлемо
    # (пользователь просто начнёт создание заново). Redis — отдельная зависимость, не берём.
    dp = Dispatcher(storage=MemoryStorage())
    dp["shop_service"] = shop_service
    dp["cipher"] = cipher
    dp.include_router(router)
    return dp
