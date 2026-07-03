"""
Загрузка конфигурации из переменных окружения.
Все секреты и настройки читаются из файла .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
FOOTBALL_DATA_API_KEY: str = os.getenv("FOOTBALL_DATA_API_KEY", "")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
DB_PATH: str = os.getenv("DB_PATH", "bot_history.db")

# Базовый URL Football-Data.org API
FOOTBALL_DATA_BASE_URL: str = "https://api.football-data.org/v4"

# Таймауты и лимиты
API_TIMEOUT: int = 10  # секунд на запрос к API
CACHE_TTL: int = 60     # секунд жизни кэша (чтобы не превысить лимит 10 запросов/мин)
MAX_HISTORY_RECORDS: int = 5  # сколько последних записей показывать в /history

def validate() -> None:
    """Проверяет, что все обязательные переменные окружения заданы."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not FOOTBALL_DATA_API_KEY:
        missing.append("FOOTBALL_DATA_API_KEY")
    if missing:
        raise EnvironmentError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}. "
            f"Скопируйте .env.example в .env и заполните значения."
        )
