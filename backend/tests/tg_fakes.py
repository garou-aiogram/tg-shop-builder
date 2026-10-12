"""Подмена сетевого слоя aiogram: все вызовы Bot API записываются, ответы — правдоподобные."""
from datetime import datetime
from itertools import count

from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

ids = count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            msg = Message(message_id=method.message_id if isinstance(method, EditMessageText) and method.message_id
                          else next(ids),
                          date=datetime.now(), chat=Chat(id=method.chat_id or 1, type="private"), text=method.text)
            return msg.as_(bot)  # как настоящий ответ: объект привязан к боту (можно .edit_text())
        if isinstance(method, (DeleteMessage, AnswerCallbackQuery)):
            return True
        raise NotImplementedError(type(method).__name__)

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        self.closed = True

    def sent(self) -> list:
        return [r for r in self.requests if isinstance(r, (SendMessage, EditMessageText))]

    def texts(self) -> list[str]:
        return [r.text for r in self.sent()]

    def reset(self) -> None:
        self.requests.clear()


def user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name="U")


def text_update(uid: int, text: str) -> Update:
    msg = Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=uid, type="private"),
                  from_user=user(uid), text=text)
    return Update(update_id=next(ids), message=msg)


def callback_update(uid: int, data: str) -> Update:
    msg = Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=uid, type="private"), text="-")
    cb = CallbackQuery(id=str(next(ids)), from_user=user(uid), chat_instance="c", message=msg, data=data)
    return Update(update_id=next(ids), callback_query=cb)
