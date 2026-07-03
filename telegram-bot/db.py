"""
Работа с базой данных SQLite.
Хранит историю запросов пользователей.
"""

from __future__ import annotations

import datetime
from typing import Any

import aiosqlite

from config import DB_PATH, MAX_HISTORY_RECORDS
from utils import get_logger

logger = get_logger(__name__)


async def init_db() -> None:
    """Создаёт таблицу истории, если её ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                prediction TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_user_id
            ON history(user_id, created_at DESC)
        """)
        await db.commit()
    logger.info("База данных инициализирована: %s", DB_PATH)


async def save_prediction(
    user_id: int,
    username: str | None,
    team1: str,
    team2: str,
    prediction: str,
    confidence: float,
) -> None:
    """
    Сохраняет прогноз в историю.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO history (user_id, username, team1, team2, prediction, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                team1,
                team2,
                prediction,
                confidence,
                datetime.datetime.now().isoformat(),
            ),
        )
        await db.commit()
    logger.debug("Прогноз сохранён для user_id=%d: %s vs %s", user_id, team1, team2)


async def get_user_history(user_id: int, limit: int = MAX_HISTORY_RECORDS) -> list[dict[str, Any]]:
    """
    Возвращает последние N записей истории для пользователя.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT team1, team2, prediction, confidence, created_at
            FROM history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
