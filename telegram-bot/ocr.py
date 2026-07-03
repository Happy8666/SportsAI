"""
Модуль распознавания текста (OCR).
Использует Tesseract через pytesseract с предобработкой изображений через OpenCV.
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image

from utils import get_logger

logger = get_logger(__name__)

# Разрешённые форматы изображений
ALLOWED_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """
    Предобработка изображения для улучшения распознавания текста:
    1. Перевод в оттенки серого
    2. Повышение контраста (CLAHE)
    3. Бинаризация (адаптивный порог)
    4. Удаление шума (медианный фильтр)
    """
    # Оттенки серого
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Повышение контраста – CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Бинаризация – адаптивный порог (OTSU + адаптивный)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Удаление шума – медианный фильтр
    denoised = cv2.medianBlur(binary, 3)

    logger.debug(
        "Предобработка: исходный размер=%s → серый+CLAHE+OTSU+median",
        image.shape,
    )
    return denoised


def extract_text(image: np.ndarray, lang: str = "eng+rus") -> str:
    """
    Извлекает текст из предобработанного изображения через Tesseract.
    lang – языки распознавания (eng+rus = английский + русский).
    """
    logger.info("Запуск OCR (языки: %s)", lang)
    pil_image = Image.fromarray(image)
    config = "--psm 6 --oem 3"  # PSM 6: блок текста, OEM 3: LSTM + Legacy
    text = pytesseract.image_to_string(pil_image, lang=lang, config=config)
    logger.info("OCR завершён, извлечено %d символов", len(text))
    return text.strip()


def find_team_names(text: str) -> list[str]:
    """
    Ищет названия команд в извлечённом тексте.
    Эвристика: ищет строки, похожие на названия (состоящие из букв, пробелов, дефисов),
    исключая типичные заголовки (Goals, Possession, Shots и т.д.).
    Возвращает список из не более чем 2 названий команд.
    """
    # Ключевые слова, которые НЕ являются названиями команд
    noise_keywords: set[str] = {
        "goals", "possession", "shots", "fouls", "corners", "offsides",
        "passes", "tackles", "saves", "yellow", "red", "card", "cards",
        "goal", "shot", "possession", "statistics", "stats", "match",
        "score", "time", "attendance", "referee", "stadium", "league",
        "home", "away", "team", "teams", "lineup", "lineups", "formation",
        "substitutes", "substitute", "coach", "minute", "minutes",
    }

    candidates: list[str] = []
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        # Пропускаем пустые строки и строки длиннее 50 символов
        if not stripped or len(stripped) > 50:
            continue
        # Пропускаем строки с цифрами (обычно статистика)
        if any(ch.isdigit() for ch in stripped):
            continue
        # Проверяем, что строка состоит из букв, пробелов и дефисов
        words = stripped.lower().split()
        if not words:
            continue
        if all(w.isalpha() or set(w).issubset({"-", "'"}) for w in words):
            # Исключаем шумовые слова
            if all(w not in noise_keywords for w in words) and len(words) <= 4:
                candidates.append(stripped)
                if len(candidates) >= 2:
                    break

    logger.info("Найдено кандидатов в названия команд: %s", candidates[:2])
    return candidates[:2]


async def process_screenshot(image_bytes: bytes) -> tuple[str | None, str | None]:
    """
    Полный пайплайн обработки скриншота:
    1. Декодирование изображения из байтов
    2. Предобработка
    3. OCR-распознавание
    4. Извлечение названий команд

    Возвращает кортеж (команда1, команда2) или (None, None) при ошибке.
    Выполняется в отдельном потоке, чтобы не блокировать event loop.
    """
    import concurrent.futures
    import asyncio

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        try:
            return await loop.run_in_executor(
                executor,
                _process_screenshot_sync,
                image_bytes,
            )
        except Exception as e:
            logger.exception("Ошибка обработки скриншота: %s", e)
            return None, None


def _process_screenshot_sync(image_bytes: bytes) -> tuple[str | None, str | None]:
    """Синхронная обёртка для обработки скриншота (запускается в потоке)."""
    # Декодирование
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image is None:
        logger.error("Не удалось декодировать изображение")
        return None, None

    logger.info("Изображение декодировано, размер: %s", image.shape)

    # Предобработка
    processed = preprocess_image(image)

    # OCR
    text = extract_text(processed)
    if not text:
        logger.warning("OCR не распознал текст")
        return None, None

    logger.debug("Распознанный текст:\n%s", text)

    # Поиск названий команд
    team_names = find_team_names(text)
    if len(team_names) < 2:
        logger.warning("Не удалось найти 2 названия команд. Найдено: %s", team_names)
        return (team_names[0] if team_names else None, None)

    return team_names[0], team_names[1]
