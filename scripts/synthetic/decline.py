"""Физика скважины: гиперболическая кривая Арпса, S-образный рост обводнённости,
рост газового фактора при прохождении давления насыщения.

Все функции векторизованы по numpy-массиву времени (в сутках от начала
разработки скважины, не от начала истории мониторинга).
"""

from __future__ import annotations

import numpy as np


def arps_hyperbolic_rate(
    t_days: np.ndarray, qi: float, b: float, di_annual: float
) -> np.ndarray:
    """Дебит нефти по Арпсу: q(t) = qi / (1 + b*Di*t)^(1/b).

    di_annual — номинальный годовой темп падения, пересчитывается в суточный.
    """
    di_daily = di_annual / 365.0
    return qi / (1.0 + b * di_daily * t_days) ** (1.0 / b)


def logistic_curve(
    t_days: np.ndarray, y_start: float, y_end: float, t_mid: float, k: float
) -> np.ndarray:
    """Общая S-образная кривая перехода от y_start к y_end с центром в t_mid."""
    return y_start + (y_end - y_start) / (1.0 + np.exp(-k * (t_days - t_mid)))


def sample_lognormal_range(
    rng: np.random.Generator, low: float, high: float, size: int
) -> np.ndarray:
    """Сэмплирует логнормальное распределение, у которого [low, high] примерно
    соответствует диапазону ±3 сигма в логарифмическом пространстве.

    Используется, когда в конфиге задан только диапазон, а не явные
    параметры распределения (mu/sigma) — упрощение для удобства конфигурации.
    """
    log_low, log_high = np.log(low), np.log(high)
    mu = (log_low + log_high) / 2.0
    sigma = (log_high - log_low) / 6.0
    values = rng.lognormal(mean=mu, sigma=sigma, size=size)
    return np.clip(values, low, high)
