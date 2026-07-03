"""
Модуль прогнозирования исходов футбольных матчей.
На основе статистики команд вычисляет вероятности и ключевые факторы.
"""

from __future__ import annotations

from typing import Any

from utils import get_logger

logger = get_logger(__name__)


def _extract_goals_stats(matches: list[dict[str, Any]], team_id: int, is_home: bool) -> dict[str, float]:
    """
    Извлекает статистику голов команды из списка матчей.
    Возвращает словарь со средними голами (забито, пропущено).
    """
    scored = 0
    conceded = 0
    count = 0

    for match in matches:
        home_id = match["homeTeam"]["id"]
        away_id = match["awayTeam"]["id"]
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]

        # Пропускаем матчи без счёта
        if home_goals is None or away_goals is None:
            continue

        if team_id == home_id:
            scored += home_goals
            conceded += away_goals
        elif team_id == away_id:
            scored += away_goals
            conceded += home_goals
        else:
            continue  # команда не участвует в этом матче (не должно случиться)
        count += 1

    if count == 0:
        return {"scored_avg": 0.0, "conceded_avg": 0.0, "matches_count": 0}

    return {
        "scored_avg": round(scored / count, 2),
        "conceded_avg": round(conceded / count, 2),
        "matches_count": count,
    }


def _extract_h2h_stats(matches: list[dict[str, Any]], team1_id: int, team2_id: int) -> dict[str, Any]:
    """
    Анализирует историю личных встреч (head-to-head).
    Возвращает количество побед каждой команды, ничьих и последний результат.
    """
    wins_team1 = 0
    wins_team2 = 0
    draws = 0
    last_result = None

    for match in matches:
        home_id = match["homeTeam"]["id"]
        away_id = match["awayTeam"]["id"]
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]

        if home_goals is None or away_goals is None:
            continue

        if home_goals > away_goals:
            if home_id == team1_id:
                wins_team1 += 1
            else:
                wins_team2 += 1
        elif away_goals > home_goals:
            if away_id == team1_id:
                wins_team1 += 1
            else:
                wins_team2 += 1
        else:
            draws += 1

        if last_result is None:
            last_result = {
                "home": match["homeTeam"].get("shortName", match["homeTeam"].get("name", "?")),
                "away": match["awayTeam"].get("shortName", match["awayTeam"].get("name", "?")),
                "score": f"{home_goals} – {away_goals}",
            }

    return {
        "wins_team1": wins_team1,
        "wins_team2": wins_team2,
        "draws": draws,
        "last_result": last_result,
    }


def _generate_factors(
    team1_stats: dict[str, float],
    team2_stats: dict[str, float],
    h2h_stats: dict[str, Any],
    home_advantage: bool,
    confidence: float,
) -> list[str]:
    """
    Генерирует 3–5 ключевых факторов, объясняющих прогноз.
    """
    factors: list[str] = []

    # Форма команды 1
    if team1_stats.get("matches_count", 0) > 0:
        scored1 = team1_stats["scored_avg"]
        conceded1 = team1_stats["conceded_avg"]
        factors.append(
            f"Форма хозяев: в среднем {scored1} гола за матч, "
            f"пропускают {conceded1} (последние {int(team1_stats['matches_count'])} игр)"
        )

    # Форма команды 2
    if team2_stats.get("matches_count", 0) > 0:
        scored2 = team2_stats["scored_avg"]
        conceded2 = team2_stats["conceded_avg"]
        factors.append(
            f"Форма гостей: в среднем {scored2} гола за матч, "
            f"пропускают {conceded2} (последние {int(team2_stats['matches_count'])} игр)"
        )

    # Преимущество домашнего поля
    if home_advantage:
        factors.append("Преимущество домашнего поля у хозяев (~15% к вероятности)")

    # История встреч
    total_h2h = h2h_stats.get("wins_team1", 0) + h2h_stats.get("wins_team2", 0) + h2h_stats.get("draws", 0)
    if total_h2h > 0:
        w1 = h2h_stats["wins_team1"]
        w2 = h2h_stats["wins_team2"]
        d = h2h_stats["draws"]
        factors.append(
            f"История встреч (последние {total_h2h}): "
            f"побед хозяев — {w1}, гостей — {w2}, ничьих — {d}"
        )
        if h2h_stats.get("last_result"):
            lr = h2h_stats["last_result"]
            factors.append(
                f"Последняя встреча: {lr['home']} {lr['score']} {lr['away']}"
            )

    # Уверенность
    if confidence >= 0.7:
        factors.append(f"Высокая уверенность прогноза ({confidence:.0%})")
    elif confidence >= 0.5:
        factors.append(f"Средняя уверенность прогноза ({confidence:.0%})")
    else:
        factors.append(f"Низкая уверенность ({confidence:.0%}) – рекомендуется дополнительный анализ")

    return factors[:5]


def predict(
    team1_name: str,
    team2_name: str,
    team1_matches: list[dict[str, Any]],
    team2_matches: list[dict[str, Any]],
    h2h_matches: list[dict[str, Any]],
    team1_id: int,
    team2_id: int,
) -> dict[str, Any]:
    """
    Рассчитывает прогноз исхода матча на основе статистики.

    Аргументы:
        team1_name – название команды хозяев
        team2_name – название команды гостей
        team1_matches – последние матчи хозяев
        team2_matches – последние матчи гостей
        h2h_matches – история личных встреч
        team1_id, team2_id – ID команд в API

    Возвращает словарь с прогнозом:
        - home_win_prob, draw_prob, away_win_prob (вероятности)
        - confidence (уверенность)
        - predicted_outcome (ожидаемый исход)
        - suggested_bet (рекомендация ставки)
        - factors (ключевые факторы)
    """
    logger.info("Расчёт прогноза: %s vs %s", team1_name, team2_name)

    # Извлекаем статистику
    stats1 = _extract_goals_stats(team1_matches, team1_id, is_home=True)
    stats2 = _extract_goals_stats(team2_matches, team2_id, is_home=False)
    h2h = _extract_h2h_stats(h2h_matches, team1_id, team2_id)

    # Рассчитываем ожидаемые голы каждой команды
    expected_home_goals = stats1["scored_avg"] * 1.15  # +15% за домашнее поле
    expected_away_goals = stats2["scored_avg"] * 0.85  # -15% за гостевой стадион

    # Базовая эвристика вероятностей
    # Если ожидаемые голы > 1.5, то выше вероятность победы
    home_strength = min(expected_home_goals, 3.0) / 3.0  # нормализуем до 0..1
    away_strength = min(expected_away_goals, 3.0) / 3.0

    # Корректировка на основе истории встреч
    h2h_total = h2h.get("wins_team1", 0) + h2h.get("wins_team2", 0) + h2h.get("draws", 0)
    h2h_home_bonus = h2h.get("wins_team1", 0) / max(h2h_total, 1) * 0.2
    h2h_away_bonus = h2h.get("wins_team2", 0) / max(h2h_total, 1) * 0.2

    # Итоговые силы (с учётом H2H)
    adjusted_home = home_strength * 0.5 + h2h_home_bonus
    adjusted_away = away_strength * 0.5 + h2h_away_bonus

    # Преобразуем в вероятности через softmax
    total_strength = adjusted_home + adjusted_away + 0.3  # 0.3 – baseline для ничьей
    if total_strength == 0:
        total_strength = 1.0

    home_win_prob = round(adjusted_home / total_strength, 3)
    away_win_prob = round(adjusted_away / total_strength, 3)
    draw_prob = round(0.3 / total_strength, 3)

    # Определяем ожидаемый исход
    if home_win_prob > away_win_prob and home_win_prob > draw_prob:
        predicted_outcome = f"Победа {team1_name}"
        suggested_bet = "1 (победа хозяев)"
    elif away_win_prob > home_win_prob and away_win_prob > draw_prob:
        predicted_outcome = f"Победа {team2_name}"
        suggested_bet = "2 (победа гостей)"
    else:
        predicted_outcome = "Ничья"
        suggested_bet = "X (ничья)"

    # Уверенность: на основе разброса вероятностей
    max_prob = max(home_win_prob, away_win_prob, draw_prob)
    sum_probs = home_win_prob + away_win_prob + draw_prob
    confidence = round(max_prob / sum_probs, 3) if sum_probs > 0 else 0.0

    # Генерируем факторы
    factors = _generate_factors(stats1, stats2, h2h, True, confidence)

    result = {
        "team1": team1_name,
        "team2": team2_name,
        "home_win_prob": home_win_prob,
        "draw_prob": draw_prob,
        "away_win_prob": away_win_prob,
        "confidence": confidence,
        "predicted_outcome": predicted_outcome,
        "suggested_bet": suggested_bet,
        "factors": factors,
        "stats": {
            "team1": stats1,
            "team2": stats2,
            "h2h": h2h,
        },
    }

    logger.info(
        "Прогноз: %s (home=%.2f, draw=%.2f, away=%.2f, confidence=%.2f)",
        predicted_outcome, home_win_prob, draw_prob, away_win_prob, confidence,
    )
    return result
