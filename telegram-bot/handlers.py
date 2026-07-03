"""
Обработчики команд и сообщений Telegram-бота.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from api_client import football_client
from config import validate, MAX_HISTORY_RECORDS
from db import init_db, save_prediction, get_user_history
from ocr import process_screenshot, ALLOWED_EXTENSIONS
from predictor import predict
from utils import (
    format_prediction_message,
    format_team_not_found,
    get_logger,
)

logger = get_logger(__name__)

router = Router()


# ───────────────────────────── /start ─────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие и краткая инструкция."""
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я <b>SportsAI</b> — бот для футбольной аналитики и прогнозов.\n\n"
        f"<b>Что я умею:</b>\n"
        f"🔹 <code>/predict Команда1 Команда2</code> — прогноз на матч\n"
        f"🔹 <b>Отправь скриншот</b> матча — распознаю команды и сделаю прогноз\n"
        f"🔹 <code>/history</code> — последние {MAX_HISTORY_RECORDS} твоих запросов\n"
        f"🔹 <code>/help</code> — подробная справка\n\n"
        f"<i>Данные предоставлены Football-Data.org</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
    logger.info("/start от user_id=%d", message.from_user.id)


# ───────────────────────────── /help ─────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Полный список команд и примеры."""
    text = (
        "📖 <b>Справка SportsAI</b>\n\n"
        "<b>Команды:</b>\n"
        "🔹 <code>/start</code> — приветствие\n"
        "🔹 <code>/help</code> — эта справка\n"
        "🔹 <code>/predict Команда1 Команда2</code> — прогноз вручную\n"
        "     Пример: <code>/predict Barcelona Real Madrid</code>\n"
        "🔹 <code>/history</code> — история твоих запросов\n\n"
        "<b>Работа со скриншотами:</b>\n"
        "• Отправь скриншот матча как фото (JPEG/PNG)\n"
        "• Бот распознает названия команд через OCR\n"
        "• Если распознать не удалось — используй <code>/predict</code> вручную\n\n"
        "<b>Как работает прогноз:</b>\n"
        "• Анализ последних 5 матчей каждой команды\n"
        "• Учёт истории личных встреч\n"
        "• Преимущество домашнего поля (+15%)\n\n"
        "<i>Данные: Football-Data.org. Не инвест-рекомендация.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
    logger.info("/help от user_id=%d", message.from_user.id)


# ─────────────────────────── /predict ────────────────────────────
@router.message(Command("predict"))
async def cmd_predict(message: Message) -> None:
    """
    Ручной прогноз по двум названиям команд.
    Пример: /predict Barcelona Real Madrid
    """
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ <b>Неверный формат.</b>\n"
            "Используйте: <code>/predict Команда1 Команда2</code>\n"
            "Пример: <code>/predict Barcelona Real Madrid</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Формат: /predict Команда1, Команда2  или  /predict Команда1 Команда2
    parts = _split_two_teams(args[1], args[2])
    if len(parts) != 2:
        await message.answer(
            "❌ Не удалось разобрать названия команд.\n"
            "Попробуйте: <code>/predict Barcelona, Real Madrid</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    team1_name, team2_name = parts[0].strip(), parts[1].strip()

    await message.answer(f"🔍 Ищу информацию о матче <b>{team1_name}</b> vs <b>{team2_name}</b>...",
                         parse_mode=ParseMode.HTML)

    result = await _do_prediction(message, team1_name, team2_name)
    if result:
        await message.answer(
            format_prediction_message(result),
            parse_mode=ParseMode.HTML,
        )


def _split_two_teams(first: str, rest: str) -> list[str]:
    """
    Разделяет аргументы команды /predict на два названия команд.
    Поддерживает разделители: ', '  в rest, а также формат «Команда1 Команда2».
    """
    # Если rest содержит разделитель — команды внутри rest
    for sep in (", ", " vs. ", " vs ", " – ", " — ", " - "):
        if sep in rest:
            return rest.split(sep, 1)
    # Если rest не содержит разделителя — first и rest = две команды
    return [first, rest]


# ──────────────────────── Обработка фото ─────────────────────────
@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """
    Обрабатывает отправленное фото (скриншот матча).
    Скачивает изображение, распознаёт названия команд, делает прогноз.
    """
    logger.info("Получено фото от user_id=%d", message.from_user.id)

    await message.answer("📸 <b>Обрабатываю скриншот...</b>", parse_mode=ParseMode.HTML)

    # Скачиваем фото в максимальном разрешении
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    logger.debug("Фото скачано: %d байт", len(image_data))

    # OCR-распознавание
    team1, team2 = await process_screenshot(image_data)

    if team1 is None or team2 is None:
        await message.answer(
            "⚠️ <b>Не удалось распознать названия команд на скриншоте.</b>\n\n"
            "Попробуйте:\n"
            "• Отправить более чёткий скриншот\n"
            "• Использовать ручной ввод: <code>/predict Команда1 Команда2</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        f"✅ Распознаны команды: <b>{team1}</b> vs <b>{team2}</b>\n"
        f"🔍 Получаю статистику...",
        parse_mode=ParseMode.HTML,
    )

    result = await _do_prediction(message, team1, team2)
    if result:
        await message.answer(
            format_prediction_message(result),
            parse_mode=ParseMode.HTML,
        )


# ─────────────────────────── /history ────────────────────────────
@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """Показывает последние 5 запросов пользователя."""
    logger.info("/history от user_id=%d", message.from_user.id)

    records = await get_user_history(message.from_user.id)

    if not records:
        await message.answer(
            "📭 <b>История пуста.</b>\n"
            "Сделайте первый прогноз через /predict или отправьте скриншот.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📋 <b>Последние {len(records)} запросов:</b>\n"]
    for i, rec in enumerate(records, 1):
        conf_percent = rec["confidence"] * 100
        lines.append(
            f"<b>{i}. {rec['team1']} vs {rec['team2']}</b>\n"
            f"   Прогноз: {rec['prediction']} | Уверенность: {conf_percent:.0f}%\n"
            f"   Дата: {rec['created_at'][:19]}\n"
        )

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ─────────────────────── Вспомогательные ─────────────────────────
async def _do_prediction(
    message: Message,
    team1_name: str,
    team2_name: str,
) -> dict[str, Any] | None:
    """
    Выполняет полный цикл прогноза: поиск команд, получение статистики,
    расчёт прогноза, сохранение в историю.
    Возвращает словарь с прогнозом или None.
    """
    # Поиск команд в API
    team1_data, team2_data = await asyncio.gather(
        football_client.search_team(team1_name),
        football_client.search_team(team2_name),
    )

    if team1_data is None:
        await message.answer(format_team_not_found(team1_name), parse_mode=ParseMode.HTML)
        return None
    if team2_data is None:
        await message.answer(format_team_not_found(team2_name), parse_mode=ParseMode.HTML)
        return None

    team1_name_api = team1_data.get("shortName") or team1_data.get("name", team1_name)
    team2_name_api = team2_data.get("shortName") or team2_data.get("name", team2_name)
    team1_id = team1_data["id"]
    team2_id = team2_data["id"]

    # Получаем статистику параллельно
    matches1, matches2, h2h = await asyncio.gather(
        football_client.get_team_matches(team1_id),
        football_client.get_team_matches(team2_id),
        football_client.get_head_to_head(team1_id, team2_id),
    )

    # Делаем прогноз
    result = predict(
        team1_name=team1_name_api,
        team2_name=team2_name_api,
        team1_matches=matches1,
        team2_matches=matches2,
        h2h_matches=h2h,
        team1_id=team1_id,
        team2_id=team2_id,
    )

    # Сохраняем в историю
    await save_prediction(
        user_id=message.from_user.id,
        username=message.from_user.username,
        team1=team1_name_api,
        team2=team2_name_api,
        prediction=result["predicted_outcome"],
        confidence=result["confidence"],
    )

    return result
