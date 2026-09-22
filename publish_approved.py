"""Publish the approved 23 September preview without another model call."""
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import daily_horoscope as bot

APPROVED_DATE = date(2026, 9, 23)


def publish_saved(folder, today):
    if today != APPROVED_DATE:
        raise ValueError('Этот одноразовый запуск разрешён только 23 сентября 2026.')
    if any(item['date'] == today.isoformat() for item in bot.read_history()):
        print('Выпуск на сегодня уже отправлен. Повтор пропущен.')
        return False
    bundles = json.loads((folder / 'preview-data.json').read_text(encoding='utf-8'))
    if not isinstance(bundles, list) or any(not isinstance(item, dict) for item in bundles):
        raise ValueError('Ожидался список выпусков.')
    matches = [item for item in bundles if item.get('date') == today.isoformat()]
    if len(matches) != 1:
        raise ValueError('Ожидался ровно один выпуск на одобренную дату.')
    bundle = matches[0]
    if bundle.get('date') != today.isoformat():
        raise ValueError('Дата сохранённого выпуска не совпадает с одобренной.')
    bot.validate(bundle['forecasts'])
    bot.validate_language(bundle['forecasts'])
    post = bot.format_edition(today, bundle['forecasts'])
    saved = (folder / f'preview-post-{today}.html').read_text(encoding='utf-8')
    if post != saved:
        raise ValueError('Текст отличается от сохранённого предпросмотра.')
    bot.publish_bundle(today, bundle)
    return True


if __name__ == '__main__':
    publish_saved(Path('approved-preview'), datetime.now(ZoneInfo('Europe/Moscow')).date())
