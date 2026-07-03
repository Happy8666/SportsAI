"""
Вспомогательные утилиты: логирование и форматирование сообщений.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from config import LOG_LEVEL

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает настроенный логгер.
    Логи пишутся одновременно в консоль (stdout) и в файл logs/bot.log.
    Файл ротируется при достижении 5 МБ, хранится до 3 бэкапов.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if not logger.handlers:
        # Формат логов
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Консольный handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Файловый handler с ротацией
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger


def format_prediction_message(prediction: dict[str, Any]) -> str:
    """
    Форматирует результат прогноза в читаемое сообщение для Telegram.
    """
    lines = [
        f"📊 <b>Прогноз: {prediction['team1']} vs {prediction['team2']}</b>",
        "",
        "⚽ <b>Вероятности:</b>",
        f"  • Победа {prediction['team1']}: {prediction['home_win_prob']:.1%}",
        f"  • Ничья: {prediction['draw_prob']:.1%}",
        f"  • Победа {prediction['team2']}: {prediction['away_win_prob']:.1%}",
        "",
        f"🎯 <b>Исход:</b> {prediction['predicted_outcome']}",
        f"💡 <b>Рекомендация:</b> {prediction['suggested_bet']}",
        f"📈 <b>Уверенность:</b> {prediction['confidence']:.0%}",
        "",
    ]

    if prediction.get("factors"):
        lines.append("🔍 <b>Ключевые факторы:</b>")
        for i, factor in enumerate(prediction["factors"], 1):
            lines.append(f"  {i}. {factor}")

    lines.append("")
    lines.append("<i>Данные предоставлены Football-Data.org. Не является инвестиционной рекомендацией.</i>")

    return "\n".join(lines)


def format_team_not_found(name: str) -> str:
    """Сообщение о том, что команда не найдена."""
    return (
        f"❌ Команда <b>«{name}»</b> не найдена в базе Football-Data.org.\n\n"
        f"Возможные причины:\n"
        f"• Опечатка в названии\n"
        f"• Команда не представлена в API\n"
        f"• Попробуйте другой вариант названия (например, «FC Barcelona» вместо «Barcelona»)\n\n"
        f"Попробуйте ещё раз через /predict или отправьте другой скриншот."
    )
