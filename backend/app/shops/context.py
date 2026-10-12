from dataclasses import dataclass

from app.services.admins import Roles


@dataclass(frozen=True)
class ShopContext:
    """Снимок магазина для обработки ОДНОГО апдейта. Читается из БД на каждый
    апдейт, поэтому смена/добавление админов действуют сразу."""

    id: int
    name: str
    roles: Roles
    bot_username: str
    webapp_url: str

    def is_admin(self, user_id: int | None) -> bool:
        return self.roles.is_admin(user_id)

    def is_main_admin(self, user_id: int | None) -> bool:
        return self.roles.is_main(user_id)
