"""Two explicitly authorized publication tests, never a recurring date override."""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import daily_horoscope as bot


def run(mode):
    if datetime.now(ZoneInfo('Europe/Moscow')).date() != date(2026, 9, 23):
        raise RuntimeError('Окно разового теста закрыто.')
    if mode not in ('saved24', 'full25'):
        raise ValueError('Неизвестный тест.')
    day = date(2026, 9, 24 if mode == 'saved24' else 25)
    history = bot.read_history()
    if any(item['date'] == str(day) for item in history):
        print('Тестовый выпуск уже опубликован; повтор пропущен.')
        return
    bot.open_generation_store(day)
    delivery = bot.GENERATION_STORE.data.get('delivery')
    if delivery:
        if delivery.get('status') != 'sent':
            raise RuntimeError('Предыдущая отправка требует проверки; повтор запрещён.')
        bot.remember(delivery['bundle'])
        return
    if mode == 'saved24':
        folder = Path('approved-preview')
        bundles = json.loads((folder / 'preview-data.json').read_text())
        if len(bundles) != 1 or bundles[0]['date'] != str(day):
            raise ValueError('Неверный сохранённый выпуск.')
        bundle = bundles[0]
        bot.validate(bundle['forecasts'])
        bot.validate_language(bundle['forecasts'])
        if bot.format_edition(day, bundle['forecasts']) != (folder / f'preview-post-{day}.html').read_text():
            raise ValueError('Сохранённый текст изменён.')
    else:
        if not any(item['date'] == '2026-09-24' for item in history):
            raise RuntimeError('Сначала должен завершиться тест сохранённого выпуска.')
        bundle = bot.generate_bundle(day, history)
    bot.publish_bundle(day, bundle)


if __name__ == '__main__':
    run(sys.argv[1])
