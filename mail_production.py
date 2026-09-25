"""Daily Mail summary publishing; shares the existing delivery guard/history."""
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import daily_horoscope as bot
import mail_preview
from generation_store import GenerationStore
from history_store import api


def run(preview=False, target=None, now=None):
    now = now or datetime.now(ZoneInfo('Europe/Moscow'))
    day = target or now.date() + timedelta(days=1)
    if not preview:
        if target is not None:
            raise ValueError('Явная дата разрешена только для предпросмотра.')
        if now.date() < date(2026, 9, 25) or now.hour < 21:
            raise RuntimeError('Публикация разрешена с 21:00 по Москве, начиная с 25 сентября.')
        if any(row['date'] == str(day) for row in bot.read_history()):
            print('Выпуск уже опубликован; повтор пропущен.')
            return
        delivery_store = GenerationStore(day, api)
        delivery = delivery_store.data.get('delivery')
        if delivery:
            if delivery.get('status') != 'sent':
                raise RuntimeError('Предыдущая отправка не подтверждена; повтор запрещён.')
            bundle = delivery['bundle']
            if bundle['date'] != str(day):
                raise ValueError('Неверная дата сохранённой отправки.')
            bot.remember(bundle)
            return
    mail_preview.run(day)
    summary_store = bot.GENERATION_STORE
    if summary_store.data.get('language_editor_version') != mail_preview.EDITOR_VERSION:
        raise RuntimeError('Пересказ не прошёл редактуру.')
    forecasts = summary_store.data['result']['forecasts']
    post = bot.format_edition(day, forecasts, markup=False)
    if preview:
        Path('preview.md').write_text(post, encoding='utf-8')
        print('Предпросмотр: отправки в Telegram нет.')
        return
    changes = summary_store.data.get('language_edit_review', {}).get('changes', [])
    bundle = {'date': str(day), 'forecasts': forecasts,
              'editorial_report': {'date': str(day), 'repair_rounds': int(bool(changes)),
                  'sign_rewrites': len({c['sign'] for c in changes}),
                  'remaining_signs': 0, 'remaining_issues': {},
                  'spent_usd_estimate': summary_store.data['spent'],
                  'budget_usd': bot.API_BUDGET.limit, 'next_round_usd_estimate': None}}
    # Generation journal is separate; delivery guard is shared with the old bot.
    bot.GENERATION_STORE = delivery_store
    bot.publish_bundle(day, bundle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--date', type=date.fromisoformat)
    args = parser.parse_args()
    run(args.preview, args.date)
