"""
Обработчики команд и сообщений Telegram-бота.
Поддерживает инлайн-кнопки главного меню и callback-запросы.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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

# ──────────────────────── Клавиатуры ────────────────────────────

POPULAR_TOURNAMENTS: list[tuple[str, str, str]] = [
    ("WC", "🏆 ЧМ", "Чемпионат мира"),
    ("EC", "🏆 Евро", "Чемпионат Европы"),
    ("CL", "⭐ ЛЧ", "Лига чемпионов"),
    ("EL", "⭐ ЛЕ", "Лига Европы"),
    ("PL", "🏴 АПЛ", "Премьер-лига"),
    ("PD", "🇪🇸 Примера", "Ла Лига"),
    ("SA", "🇮🇹 Серия А", "Серия А"),
    ("BL1", "🇩🇪 Бундеслига", "Бундеслига"),
    ("FL1", "🇫🇷 Лига 1", "Лига 1"),
    ("ELC", "🏴 Чемпионшип", "Чемпионшип"),
    ("DED", "🇳🇱 Эредивизи", "Эредивизи"),
    ("MLS", "🇺🇸 МЛС", "MLS"),
    ("BSA", "🇧🇷 Бразилия", "Серия А Бразилии"),
    ("UNL", "🏆 Лига Наций", "Лига наций УЕФА"),
]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Прогноз на матч", callback_data="menu:predict")],
        [InlineKeyboardButton(text="📅 Матчи турниров", callback_data="menu:tournaments")],
        [
            InlineKeyboardButton(text="📋 История", callback_data="menu:history"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
        ],
    ])


def tournaments_keyboard() -> InlineKeyboardMarkup:
    """Меню выбора турнира."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label, _ in POPULAR_TOURNAMENTS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"tournament:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ───────────────────────────── /start ─────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие и главное меню."""
    text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        f"Я <b>SportsAI</b> — бот для футбольной аналитики и прогнозов.\n\n"
        f"<b>Что я умею:</b>\n"
        f"🔹 Делать прогнозы на матчи\n"
        f"🔹 Показывать ближайшие матчи турниров\n"
        f"🔹 Распознавать команды со скриншотов\n"
        f"🔹 Запоминать твою историю запросов\n\n"
        f"<i>Выбери действие в меню или просто напиши названия двух команд!</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    logger.info("/start от user_id=%d", message.from_user.id)


# ─────────────────────── Callback-обработчики ──────────────────────

@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\nВыбери действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:predict")
async def cb_menu_predict(callback: CallbackQuery) -> None:
    """Показывает инструкцию по прогнозу."""
    text = (
        "📊 <b>Прогноз на матч</b>\n\n"
        "<b>3 способа получить прогноз:</b>\n\n"
        "1️⃣ <b>Напиши названия команд</b>\n"
        "<i>Пример:</i> <code>Испания Австрия</code>\n"
        "<i>Пример:</i> <code>Barcelona vs Real Madrid</code>\n\n"
        "2️⃣ <b>Используй команду</b>\n"
        "<code>/predict Команда1 Команда2</code>\n\n"
        "3️⃣ <b>Отправь скриншот матча</b>\n"
        "Бот распознает команды с фото и сделает прогноз\n\n"
        "<i>Введи названия двух команд в следующем сообщении</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:tournaments")
async def cb_menu_tournaments(callback: CallbackQuery) -> None:
    """Показывает меню выбора турнира."""
    await callback.message.edit_text(
        "📅 <b>Выбери турнир</b> для просмотра ближайших матчей:",
        parse_mode=ParseMode.HTML,
        reply_markup=tournaments_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    """Показывает историю запросов."""
    records = await get_user_history(callback.from_user.id)

    if not records:
        await callback.message.edit_text(
            "📭 <b>История пуста.</b>\n\nСделайте первый прогноз — через меню или просто написав названия команд!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
            ]),
        )
        await callback.answer()
        return

    lines = [f"📋 <b>Последние {len(records)} запросов:</b>\n"]
    for i, rec in enumerate(records, 1):
        conf_percent = rec["confidence"] * 100
        lines.append(
            f"<b>{i}. {rec['team1']} vs {rec['team2']}</b>\n"
            f"   {rec['prediction']} | Уверенность: {conf_percent:.0f}%\n"
            f"   {rec['created_at'][:19]}\n"
        )

    lines.append("")
    lines.append("<i>Нажми «Назад» для возврата в меню</i>")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def cb_menu_help(callback: CallbackQuery) -> None:
    """Показывает справку."""
    text = (
        "📖 <b>Справка SportsAI</b>\n\n"
        "<b>Как получить прогноз:</b>\n"
        "• Напиши <code>Команда1 Команда2</code>\n"
        "• Или <code>/predict Команда1 Команда2</code>\n"
        "• Или отправь скриншот матча\n\n"
        "<b>Турниры:</b>\n"
        "• Нажми <b>📅 Матчи турниров</b> в меню\n"
        "• Или <code>/matches ЧМ</code>\n\n"
        "<b>Как работает прогноз:</b>\n"
        "• Анализ последних 5 матчей каждой команды\n"
        "• Учёт истории личных встреч\n"
        "• Преимущество домашнего поля (+15%)\n\n"
        "<i>Данные: Football-Data.org. Не инвест-рекомендация.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tournament:"))
async def cb_tournament_matches(callback: CallbackQuery) -> None:
    """Показывает матчи выбранного турнира."""
    from team_mapping import get_competition_name

    code = callback.data.split(":", 1)[1]
    comp_name = get_competition_name(code)

    await callback.message.edit_text(
        f"🔍 Загружаю матчи <b>{comp_name}</b>...",
        parse_mode=ParseMode.HTML,
    )

    matches = await football_client.get_upcoming_matches(code, limit=8)

    if not matches:
        await callback.message.edit_text(
            f"📭 <b>{comp_name}</b> — нет ближайших матчей в базе.\n"
            f"Возможно, сезон ещё не начался или завершился.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К турнирам", callback_data="menu:tournaments")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
            ]),
        )
        await callback.answer()
        return

    lines = [f"📅 <b>{comp_name} — ближайшие матчи:</b>\n"]
    for match in matches:
        home = match["homeTeam"].get("shortName") or match["homeTeam"].get("name", "?")
        away = match["awayTeam"].get("shortName") or match["awayTeam"].get("name", "?")
        utc_date = match.get("utcDate", "")
        status = match.get("status", "")
        score = match.get("score", {}).get("fullTime", {})

        try:
            dt = datetime.datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%d.%m %H:%M")
        except (ValueError, TypeError):
            date_str = utc_date[:16] if utc_date else "?"

        status_emoji = "🟢" if status == "LIVE" else ("✅" if status == "FINISHED" else "⏳")
        score_str = ""
        if status == "FINISHED" and score.get("home") is not None:
            score_str = f"  <b>{score['home']}–{score['away']}</b>"
        elif status == "LIVE" and score.get("home") is not None:
            score_str = f"  🔴 <b>{score['home']}–{score['away']}</b>"

        lines.append(
            f"{status_emoji} <b>{home}</b> — <b>{away}</b>{score_str}\n"
            f"   📆 {date_str} (МСК)"
        )

    lines.append("")
    lines.append("<i>Скопируй названия команд и отправь их в чат для прогноза</i>")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К турнирам", callback_data="menu:tournaments")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]),
    )
    await callback.answer()


# ──────────────────────────── КОМАНДЫ ────────────────────────────

@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    """Показывает главное меню с кнопками."""
    await message.answer(
        "🏠 <b>Главное меню</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Полный список команд и примеры."""
    text = (
        "📖 <b>Справка SportsAI</b>\n\n"
        "<b>Как получить прогноз:</b>\n"
        "• Напиши <code>Команда1 Команда2</code>\n"
        "• Команда <code>/predict Команда1 Команда2</code>\n"
        "• Отправь скриншот матча\n\n"
        "<b>Команды:</b>\n"
        "🔹 <code>/start</code> — главное меню\n"
        "🔹 <code>/menu</code> — меню с кнопками\n"
        "🔹 <code>/predict</code> — прогноз на матч\n"
        "🔹 <code>/matches ЧМ</code> — матчи турнира\n"
        "🔹 <code>/history</code> — история запросов\n"
        "🔹 <code>/help</code> — эта справка\n\n"
        "<i>Данные: Football-Data.org. Не инвест-рекомендация.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
    logger.info("/help от user_id=%d", message.from_user.id)


@router.message(Command("predict"))
async def cmd_predict(message: Message) -> None:
    """Ручной прогноз по двум названиям команд."""
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ <b>Неверный формат.</b>\n\n"
            "Используйте: <code>/predict Команда1 Команда2</code>\n"
            "<i>Или просто напишите названия двух команд в чат!</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    parts = _split_two_teams(args[1], args[2])
    if len(parts) != 2:
        await message.answer(
            "❌ Не удалось разобрать названия команд.\n"
            "Попробуйте: <code>/predict Barcelona, Real Madrid</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await _predict_and_respond(message, parts[0].strip(), parts[1].strip())


@router.message(Command("matches"))
async def cmd_matches(message: Message) -> None:
    """Показывает ближайшие матчи турнира через кнопки или текст."""
    from team_mapping import translate_competition, get_competition_name

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📅 <b>Выбери турнир:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=tournaments_keyboard(),
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
    await _show_matches(message, code, comp_name)


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """Показывает последние 5 запросов пользователя."""
    logger.info("/history от user_id=%d", message.from_user.id)

    records = await get_user_history(message.from_user.id)

    if not records:
        await message.answer(
            "📭 <b>История пуста.</b>\n"
            "Сделайте первый прогноз — через меню или просто написав названия команд!",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"📋 <b>Последние {len(records)} запросов:</b>\n"]
    for i, rec in enumerate(records, 1):
        conf_percent = rec["confidence"] * 100
        lines.append(
            f"<b>{i}. {rec['team1']} vs {rec['team2']}</b>\n"
            f"   {rec['prediction']} | Уверенность: {conf_percent:.0f}%\n"
            f"   {rec['created_at'][:19]}\n"
        )

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ──────────────────────── Обработка фото ─────────────────────────

@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обрабатывает отправленное фото — скриншот матча."""
    logger.info("Получено фото от user_id=%d", message.from_user.id)

    await message.answer("📸 <b>Обрабатываю скриншот...</b>", parse_mode=ParseMode.HTML)

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()

    logger.debug("Фото скачано: %d байт", len(image_data))

    team1, team2 = await process_screenshot(image_data)

    if team1 is None or team2 is None:
        await message.answer(
            "⚠️ <b>Не удалось распознать названия команд на скриншоте.</b>\n\n"
            "Попробуйте:\n"
            "• Отправить более чёткий скриншот\n"
            "• Написать <code>/predict Команда1 Команда2</code>\n"
            "• Или просто написать названия команд в чат",
            parse_mode=ParseMode.HTML,
        )
        return

    await message.answer(
        f"✅ Распознаны команды: <b>{team1}</b> vs <b>{team2}</b>\n🔍 Получаю статистику...",
        parse_mode=ParseMode.HTML,
    )

    await _predict_and_respond(message, team1, team2)


# ─────────────────── Обработка обычного текста ──────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    """Обрабатывает обычный текст как названия команд для прогноза."""
    text = message.text.strip()

    if len(text) < 3 or len(text) > 80:
        return

    parts = _split_two_teams_text(text)
    if len(parts) != 2:
        return

    team1_name, team2_name = parts[0].strip(), parts[1].strip()
    if not team1_name or not team2_name:
        return

    logger.info("Текстовый прогноз: %s vs %s от user_id=%d", team1_name, team2_name, message.from_user.id)
    await _predict_and_respond(message, team1_name, team2_name)


# ─────────────────────── Вспомогательные ─────────────────────────

def _split_two_teams(first: str, rest: str) -> list[str]:
    """Разделяет аргументы /predict на две команды."""
    for sep in (", ", " vs. ", " vs ", " – ", " — ", " - "):
        if sep in rest:
            return rest.split(sep, 1)
    return [first, rest]


def _split_two_teams_text(text: str) -> list[str]:
    """Разделяет произвольный текст на два названия команд."""
    for sep in (", ", " vs. ", " vs ", " – ", " — ", " - "):
        if sep in text:
            return text.split(sep, 1)
    words = text.split()
    if len(words) < 2:
        return [text]
    for split_at in (2, 1):
        if split_at < len(words):
            team1 = " ".join(words[:split_at])
            team2 = " ".join(words[split_at:])
            if team1 and team2:
                return [team1, team2]
    return [text]


async def _predict_and_respond(message: Message, team1_name: str, team2_name: str) -> None:
    """Делает прогноз и отправляет результат."""
    await message.answer(f"🔍 Ищу <b>{team1_name}</b> vs <b>{team2_name}</b>...", parse_mode=ParseMode.HTML)
    result = await _do_prediction(message, team1_name, team2_name)
    if result:
        await message.answer(
            format_prediction_message(result),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )


async def _show_matches(message: Message, code: str, comp_name: str) -> None:
    """Показывает матчи турнира."""
    matches = await football_client.get_upcoming_matches(code, limit=8)

    if not matches:
        await message.answer(
            f"📭 <b>{comp_name}</b> — нет ближайших матчей в базе.",
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

        try:
            dt = datetime.datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%d.%m %H:%M")
        except (ValueError, TypeError):
            date_str = utc_date[:16] if utc_date else "?"

        status_emoji = "🟢" if status == "LIVE" else ("✅" if status == "FINISHED" else "⏳")
        score_str = ""
        if status == "FINISHED" and score.get("home") is not None:
            score_str = f"  <b>{score['home']}–{score['away']}</b>"
        elif status == "LIVE" and score.get("home") is not None:
            score_str = f"  🔴 <b>{score['home']}–{score['away']}</b>"

        lines.append(
            f"{status_emoji} <b>{home}</b> — <b>{away}</b>{score_str}\n"
            f"   📆 {date_str} (МСК)"
        )

    lines.append("")
    lines.append("<i>Скопируй названия и отправь в чат → получишь прогноз</i>")

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _do_prediction(
    message: Message,
    team1_name: str,
    team2_name: str,
) -> dict[str, Any] | None:
    """
    Выполняет полный цикл прогноза: поиск команд, получение статистики,
    расчёт прогноза, сохранение в историю.
    """
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

    matches1, matches2, h2h = await asyncio.gather(
        football_client.get_team_matches(team1_id),
        football_client.get_team_matches(team2_id),
        football_client.get_head_to_head(team1_id, team2_id),
    )

    result = predict(
        team1_name=team1_name_api,
        team2_name=team2_name_api,
        team1_matches=matches1,
        team2_matches=matches2,
        h2h_matches=h2h,
        team1_id=team1_id,
        team2_id=team2_id,
    )

    await save_prediction(
        user_id=message.from_user.id,
        username=message.from_user.username,
        team1=team1_name_api,
        team2=team2_name_api,
        prediction=result["predicted_outcome"],
        confidence=result["confidence"],
    )

    return result
