# TG Shop Builder — MVP

Мультитенантный конструктор интернет-магазинов в Telegram: бот-конструктор + Mini App.
Полная инструкция по запуску появится на этапе 7.

## Быстрый старт (черновик)

```bash
cp .env.example .env      # заполнить BUILDER_BOT_TOKEN, PUBLIC_URL, FERNET_KEY, WEBHOOK_SECRET, POSTGRES_PASSWORD
docker compose up --build
```

## Тесты (backend)

Нужен отдельный пустой PostgreSQL — тесты полностью пересоздают в нём схему.

```bash
cd backend
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://shop:shop@localhost:5432/shop_test pytest -v
```
