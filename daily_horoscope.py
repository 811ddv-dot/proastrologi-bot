#!/usr/bin/env python3
"""Publish 12 original daily horoscope posts to a Telegram channel.

No paid AI or third-party API is used.  A repeatable date-based combination of
original editorial fragments makes each calendar day different.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo


MOSCOW = ZoneInfo("Europe/Moscow")
SIGNS = (
    ("♈️", "Овен"), ("♉️", "Телец"), ("♊️", "Близнецы"),
    ("♋️", "Рак"), ("♌️", "Лев"), ("♍️", "Дева"),
    ("♎️", "Весы"), ("♏️", "Скорпион"), ("♐️", "Стрелец"),
    ("♑️", "Козерог"), ("♒️", "Водолей"), ("♓️", "Рыбы"),
)

OPENERS = (
    "День просит не спешить с выводами: в деталях скрыта полезная подсказка.",
    "Темп дня меняется быстро, но вы сумеете сохранить верное направление.",
    "Сегодня особенно заметно, какие привычные дела пора сделать проще.",
    "Интуиция работает точно, если дать себе несколько минут тишины.",
    "Небольшая инициатива сейчас способна запустить приятные перемены.",
    "Лучший результат принесёт не рывок, а спокойная последовательность.",
)
WORK = (
    "В делах полезно сначала закрыть одну давнюю задачу, а уже потом соглашаться на новое.",
    "Рабочий разговор сложится удачно, если заранее сформулировать главное в двух-трёх фразах.",
    "Не распыляйтесь: один приоритет, доведённый до конца, даст больше, чем десять начатых идей.",
    "Финансовые решения лучше перепроверить: сегодня внимательность ценнее скорости.",
    "Коллеги или партнёры могут предложить интересный ход — прислушайтесь, но оставьте себе время на выбор.",
    "Смелая идея заслуживает первого практического шага, даже если пока не виден весь маршрут.",
)
LOVE = (
    "В отношениях поможет прямой и мягкий разговор без попытки угадать мысли другого человека.",
    "Тёплый знак внимания сегодня будет значить больше, чем длинные объяснения.",
    "Не отвечайте на резкое слово сразу: пауза сохранит близость и ясность.",
    "Встреча или случайная переписка могут вернуть хорошее настроение.",
    "Поддержите того, кто рядом: ваше участие заметят и обязательно запомнят.",
    "Вечер подходит для лёгкой встречи, прогулки или спокойного времени с близкими.",
)
TIPS = (
    "Совет дня: оставьте в плане одно свободное окно — оно пригодится.",
    "Совет дня: не обещайте больше, чем действительно готовы сделать.",
    "Совет дня: начните утро с самого короткого, но важного дела.",
    "Совет дня: доверяйте фактам, а не тревожным предположениям.",
    "Совет дня: порадуйте себя чем-то простым и красивым.",
    "Совет дня: берегите энергию и не берите на себя чужую спешку.",
)


def choice(items: tuple[str, ...], day: date, sign: str, section: str) -> str:
    key = f"{day.isoformat()}:{sign}:{section}".encode()
    return items[int(hashlib.sha256(key).hexdigest(), 16) % len(items)]


def forecast(day: date, symbol: str, sign: str) -> str:
    return (
        f"{symbol} <b>{sign} — {day.strftime('%d.%m.%Y')}</b>\n\n"
        f"{choice(OPENERS, day, sign, 'opener')}\n\n"
        f"💼 <b>Дела и деньги.</b> {choice(WORK, day, sign, 'work')}\n\n"
        f"💞 <b>Отношения.</b> {choice(LOVE, day, sign, 'love')}\n\n"
        f"✨ {choice(TIPS, day, sign, 'tip')}\n\n"
        "#гороскоп #" + sign.lower()
    )


def telegram(method: str, fields: dict[str, str]) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    payload = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=payload, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    if not body.get("ok"):
        raise RuntimeError(body)


def main() -> None:
    channel = os.environ.get("TELEGRAM_CHANNEL", "@proastrologi")
    today = datetime.now(MOSCOW).date()
    for symbol, sign in SIGNS:
        telegram("sendMessage", {"chat_id": channel, "text": forecast(today, symbol, sign), "parse_mode": "HTML"})
        time.sleep(1)


if __name__ == "__main__":
    main()
