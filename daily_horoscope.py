import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

SIGNS = (("♈️", "Овен"), ("♉️", "Телец"), ("♊️", "Близнецы"), ("♋️", "Рак"), ("♌️", "Лев"), ("♍️", "Дева"), ("♎️", "Весы"), ("♏️", "Скорпион"), ("♐️", "Стрелец"), ("♑️", "Козерог"), ("♒️", "Водолей"), ("♓️", "Рыбы"))
OPENERS = ("День просит не спешить с выводами: в деталях скрыта полезная подсказка.", "Сегодня небольшая инициатива способна запустить приятные перемены.", "Интуиция работает точно, если дать себе несколько минут тишины.")
WORK = ("В делах сначала закройте одну давнюю задачу, а затем соглашайтесь на новое.", "Не распыляйтесь: один приоритет, доведённый до конца, даст больше десяти начатых идей.", "Финансовые решения лучше перепроверить: внимательность сегодня ценнее скорости.")
LOVE = ("В отношениях поможет прямой и мягкий разговор без попытки угадать мысли другого человека.", "Тёплый знак внимания сегодня будет значить больше, чем длинные объяснения.", "Вечер подходит для лёгкой встречи, прогулки или спокойного времени с близкими.")
TIPS = ("Совет дня: оставьте в плане одно свободное окно — оно пригодится.", "Совет дня: доверяйте фактам, а не тревожным предположениям.", "Совет дня: берегите энергию и не берите на себя чужую спешку.")

def pick(items, day, sign, section):
    n = int(hashlib.sha256(f"{day}:{sign}:{section}".encode()).hexdigest(), 16)
    return items[n % len(items)]

def message(day, icon, sign):
    return f"{icon} <b>{sign} — {day:%d.%m.%Y}</b>\n\n{pick(OPENERS, day, sign, 'a')}\n\n💼 <b>Дела и деньги.</b> {pick(WORK, day, sign, 'b')}\n\n💞 <b>Отношения.</b> {pick(LOVE, day, sign, 'c')}\n\n✨ {pick(TIPS, day, sign, 'd')}\n\n#гороскоп #{sign.lower()}"

def send(fields):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=urllib.parse.urlencode(fields).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        if not json.loads(response.read()).get("ok"): raise RuntimeError("Telegram rejected the post")

day = datetime.now(ZoneInfo("Europe/Moscow")).date()
for icon, sign in SIGNS:
    send({"chat_id": "@proastrologi", "text": message(day, icon, sign), "parse_mode": "HTML"})
    time.sleep(1)
