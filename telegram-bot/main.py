"""
Точка входа Telegram-бота SportsAI.
Запускает aiogram-бота с long polling и health-check HTTP-сервер для Render.com.
"""

from __future__ import annotations

import asyncio
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from api_client import football_client
from config import TELEGRAM_BOT_TOKEN, validate
from db import init_db
from handlers import router
from utils import get_logger

logger = get_logger("main")

# Порт для health-check (Render.com передаёт PORT в переменной окружения)
HEALTH_PORT: int = int(os.getenv("PORT", "10000"))


async def health_check(request: web.Request) -> web.Response:
    """Health-check эндпоинт для Render.com."""
    return web.Response(text="OK", status=200)


async def run_health_server() -> None:
    """Запускает простой HTTP-сервер для health-check."""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    logger.info("Health-check сервер запущен на порту %d", HEALTH_PORT)


async def on_startup() -> None:
    """Действия при запуске бота."""
    logger.info("=" * 50)
    logger.info("SportsAI Bot запускается...")
    logger.info("=" * 50)

    validate()
    await init_db()
    await run_health_server()
    logger.info("Бот готов к работе")


async def on_shutdown() -> None:
    """Действия при остановке бота."""
    logger.info("Бот останавливается...")
    await football_client.close()
    logger.info("Бот остановлен")


async def main() -> None:
    """Главная функция запуска бота."""
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Запуск long polling...")
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки")
    except Exception:
        logger.exception("Критическая ошибка бота")
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
