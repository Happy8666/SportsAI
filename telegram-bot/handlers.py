"""
Обработчики команд и сообщений Telegram-бота.
"""

from __future__ import annotations

import asyncio
import datetime
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
        f"🔹 <b>Просто напиши</b> «Испания Австрия» — я сам сделаю прогноз!\n"
        f"🔹 <b>Отправь скриншот</b> матча — распознаю команды и сделаю прогноз\n"
        f"🔹 <code>/matches ЧМ</code> — ближайшие матчи турнира\n"
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
        "🔹 <code>/history</code> — история твоих запросов\n"
        "🔹 <code>/matches Турнир</code> — ближайшие матчи\n"
        "     Пример: <code>/matches ЧМ</code>, <code>/matches АПЛ</code>\n\n"
        "<b>Текстовый прогноз:</b>\n"
        "• Просто напиши «Испания Австрия» или «Barcelona vs Real Madrid»\n"
        "• Бот сам поймёт, что это названия команд, и сделает прогноз\n\n"
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


# ─────────────────────── /matches ─────────────────────────
@router.message(Command("matches"))
async def cmd_matches(message: Message) -> None:
    """
    Показывает ближайшие матчи турнира.
    Пример: /matches ЧМ, /matches АПЛ, /matches Лига Чемпионов
    """
    from team_mapping import translate_competition, get_competition_name

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ <b>Укажите турнир.</b>\n\n"
            "<b>Примеры:</b>\n"
            "• <code>/matches ЧМ</code> — Чемпионат мира\n"
            "• <code>/matches ЛЧ</code> — Лига чемпионов\n"
            "• <code>/matches АПЛ</code> — Английская Премьер-лига\n"
            "• <code>/matches Примера</code> — Ла Лига\n"
            "• <code>/matches Бундеслига</code> — Бундеслига\n"
            "• <code>/matches Серия А</code> — Серия А\n"
            "• <code>/matches Лига 1</code> — Лига 1\n\n"
            "<i>Поддерживаются также: Евро, Лига Европы, Чемпионшип, Эредивизи, МЛС, Лига Наций</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    competition = args[1].strip()
    code = translate_competition(competition)

    if code is None:
        await message.answer(
            f"❌ Турнир <b>«{competition}»</b> не найден.\n"
            f"Попробуйте: ЧМ, ЛЧ, АПЛ, Примера, Бундеслига, Серия А, Лига 1, Евро",
            parse_mode=ParseMode.HTML,
        )
        return

    comp_name = get_competition_name(code)
    await message.answer(f"🔍 Загружаю матчи <b>{comp_name}</b>...", parse_mode=ParseMode.HTML)

    matches = await football_client.get_upcoming_matches(code, limit=8)

    if not matches:
        await message.answer(
            f"📭 <b>{comp_name}</b> — нет ближайших матчей в базе.\n"
            f"Возможно, сезон ещё не начался или API не предоставляет данные.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📅 <b>{comp_name} — ближайшие матчи:</b>\n"]
    for match in matches:
        home = match["homeTeam"].get("shortName") or match["homeTeam"].get("name", "?")
        away = match["awayTeam"].get("shortName") or match["awayTeam"].get("name", "?")
        utc_date = match.get("utcDate", "")
        status = match.get("status", "")
        score = match.get("score", {}).get("fullTime", {})

        # Форматируем дату
        try:
            dt = datetime.datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%d.%m %H:%M")
        except (ValueError, TypeError):
            date_str = utc_date[:16] if utc_date else "?"
        # Статус
        status_emoji = "🟢" if status == "LIVE" else ("✅" if status == "FINISHED" else "⏳")
        score_str = ""
        if status == "FINISHED" and score.get("home") is not None:
            score_str = f" <b>{score['home']} – {score['away']}</b>"
        elif status == "LIVE" and score.get("home") is not None:
            score_str = f" 🔴 <b>{score['home']} – {score['away']}</b>"

        lines.append(
            f"{status_emoji} <b>{home}</b> vs <b>{away}</b>{score_str}\n"
            f"   📆 {date_str} (МСК: +2ч)"
        )

    lines.append("")
    lines.append("<i>Нажми на любой матч и отправь названия команд для прогноза через /predict</i>")

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
    logger.info("/matches %s от user_id=%d", competition, message.from_user.id)


# ─────────────────── Обработка обычного текста ──────────────────
@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    """
    Обрабатывает обычный текст как названия команд.
    Примеры: «Испания Австрия», «Barcelona vs Real Madrid», «Манчестер Сити, Ливерпуль»
    """
    text = message.text.strip()
    # Слишком длинный или слишком короткий текст — не пробуем парсить
    if len(text) < 3 or len(text) > 80:
        return

    parts = _split_two_teams_text(text)
    if len(parts) != 2:
        return

    team1_name, team2_name = parts[0].strip(), parts[1].strip()
    if not team1_name or not team2_name:
        return

    logger.info("Текстовый прогноз: %s vs %s от user_id=%d", team1_name, team2_name, message.from_user.id)

    await message.answer(f"🔍 Ищу <b>{team1_name}</b> vs <b>{team2_name}</b>...", parse_mode=ParseMode.HTML)

    result = await _do_prediction(message, team1_name, team2_name)
    if result:
        await message.answer(
            format_prediction_message(result),
            parse_mode=ParseMode.HTML,
        )


def _split_two_teams_text(text: str) -> list[str]:
    """Разделяет произвольный текст на два названия команд."""
    for sep in (", ", " vs. ", " vs ", " – ", " — ", " - "):
        if sep in text:
            return text.split(sep, 1)
    # Без разделителя — берём первые 2 слова как первую команду, остальное как вторую
    # (эвристика: большинство команд — это 1-2 слова)
    words = text.split()
    if len(words) < 2:
        return [text]
    # Ищем оптимальное деление: первая команда — первые 1-2 слова
    for split_at in (2, 1):
        if split_at < len(words):
            team1 = " ".join(words[:split_at])
            team2 = " ".join(words[split_at:])
            if team1 and team2:
                return [team1, team2]
    return [text]


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
