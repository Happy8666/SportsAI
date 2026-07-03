"""
Клиент для Football-Data.org API.
Реализует поиск команд, получение статистики последних матчей и истории встреч.
Использует in-memory TTL-кэш для соблюдения лимита 10 запросов/мин.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from config import FOOTBALL_DATA_API_KEY, FOOTBALL_DATA_BASE_URL, API_TIMEOUT, CACHE_TTL
from utils import get_logger

logger = get_logger(__name__)


class CacheEntry:
    """Запись в кэше с TTL."""
    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: int = CACHE_TTL) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_expired(self) -> bool:
        """Проверяет, истёк ли TTL записи."""
        return time.monotonic() > self.expires_at


class FootballDataClient:
    """Асинхронный клиент для Football-Data.org API."""

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """Ленивая инициализация HTTP-сессии."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Auth-Token": FOOTBALL_DATA_API_KEY},
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            )
        return self._session

    async def close(self) -> None:
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _cache_get(self, key: str) -> Any | None:
        """Возвращает данные из кэша, если запись не истекла."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._cache[key]
            return None
        return entry.data

    def _cache_set(self, key: str, data: Any) -> None:
        """Сохраняет данные в кэш."""
        self._cache[key] = CacheEntry(data)

    async def _request(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        """
        Выполняет GET-запрос к API с кэшированием.
        Возвращает распарсенный JSON или None при ошибке.
        """
        url = f"{FOOTBALL_DATA_BASE_URL}{endpoint}"
        cache_key = f"{url}:{params}"

        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("Кэш-попадание: %s", url)
            return cached

        logger.debug("Запрос к API: %s params=%s", url, params)
        for attempt in range(3):
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning("Rate limit (429). Ожидание %d сек...", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if response.status == 404:
                        logger.warning("Команда/ресурс не найден: %s", url)
                        return None
                    if response.status >= 400:
                        logger.error("Ошибка API %d: %s", response.status, await response.text())
                        return None
                    data = await response.json()
                    self._cache_set(cache_key, data)
                    return data
            except asyncio.TimeoutError:
                logger.warning("Таймаут запроса (попытка %d/3): %s", attempt + 1, url)
            except aiohttp.ClientError as e:
                logger.error("Ошибка сети (попытка %d/3): %s", attempt + 1, e)
            if attempt < 2:
                await asyncio.sleep(1 * (attempt + 1))
        return None

    async def search_team(self, name: str) -> dict[str, Any] | None:
        """
        Поиск команды по названию.
        Сначала пробует перевести русское название в английское.
        Затем ищет лучший результат, проверяя схожесть названий.
        Возвращает лучший результат или None.
        """
        from team_mapping import translate_team_name

        # Переводим русское название в английское
        search_name = translate_team_name(name)
        logger.info("Поиск команды: %s → %s", name, search_name)

        data = await self._request("/teams", params={"name": search_name})
        if data and data.get("teams"):
            teams = data["teams"]
            # Ищем лучший результат по схожести названия
            best = self._find_best_match(teams, search_name)
            if best:
                logger.info("Найдена команда: %s (ID: %d)", best.get("name"), best.get("id"))
                return best

        # Если через перевод не нашли — пробуем оригинальное название
        if search_name != name:
            logger.info("Повторный поиск с оригинальным названием: %s", name)
            data = await self._request("/teams", params={"name": name})
            if data and data.get("teams"):
                best = self._find_best_match(data["teams"], name)
                if best:
                    logger.info("Найдена команда: %s (ID: %d)", best.get("name"), best.get("id"))
                    return best

        return None

    @staticmethod
    def _find_best_match(teams: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
        """
        Выбирает лучший результат из списка команд по схожести названия с запросом.
        Если все результаты сильно отличаются — возвращает None.
        """
        if not teams:
            return None

        query_lower = query.lower()
        best_team = None
        best_score = 0

        for team in teams:
            name = (team.get("name") or "").lower()
            short_name = (team.get("shortName") or "").lower()

            # Простая оценка схожести: сколько слов запроса содержится в названии команды
            query_words = set(query_lower.split())
            name_words = set(name.split())
            short_words = set(short_name.split())

            common_with_name = len(query_words & name_words)
            common_with_short = len(query_words & short_words)
            score = max(common_with_name, common_with_short)

            if score > best_score:
                best_score = score
                best_team = team

        # Требуем хотя бы 1 совпадающее слово или точное совпадение хотя бы одного слова
        if best_score == 0 and query_lower not in (best_team.get("name", "").lower(), (best_team.get("shortName", "").lower())):
            logger.warning(
                "Слабые совпадения для '%s'. Лучший: %s (score=%d)",
                query, best_team.get("name"), best_score,
            )
            # Если вообще нет совпадений — возвращаем None вместо мусора
            return None

        return best_team

    async def get_team_matches(self, team_id: int, limit: int = 5, status: str = "FINISHED") -> list[dict[str, Any]]:
        """
        Получает последние завершённые матчи команды.
        limit – максимальное количество матчей.
        """
        logger.info("Получение матчей команды ID=%d (limit=%d)", team_id, limit)
        data = await self._request(
            f"/teams/{team_id}/matches",
            params={"limit": str(limit), "status": status},
        )
        if data and data.get("matches"):
            matches = data["matches"][:limit]
            logger.info("Получено %d матчей для команды ID=%d", len(matches), team_id)
            return matches
        return []

    async def get_head_to_head(self, team1_id: int, team2_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """
        Получает историю личных встреч двух команд.
        """
        logger.info("Получение истории встреч: team1=%d, team2=%d", team1_id, team2_id)
        data = await self._request(
            "/matches",
            params={
                "team_ids": f"{team1_id},{team2_id}",
                "limit": str(limit),
                "status": "FINISHED",
            },
        )
        if data and data.get("matches"):
            return data["matches"][:limit]
        return []


# Глобальный экземпляр клиента
football_client = FootballDataClient()
