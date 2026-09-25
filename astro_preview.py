"""Isolated $1 preview experiment. No Telegram credentials or publication path."""
import argparse
import json
import os
import re
from pathlib import Path
from datetime import date
import daily_horoscope as bot
from astro_context import calculate
from generation_store import GenerationStore
from history_store import api

PROMPT = '''Напиши оригинальный развлекательный гороскоп по астрономическим данным на указанную дату.
Сначала интерпретируй данные для каждого знака через заданные солнечные дома и управителя.
Это условная астрологическая традиция, не научное предсказание и не персональная натальная карта.
Не выдумывай положения планет, аспекты, затмения, точные события или причины, отсутствующие в данных.
Подача: простой связный русский язык журнального прогноза, без копирования чужих текстов.
Разрешены понятные возможные ситуации: приглашение, разговор, небольшая покупка, встреча,
совместное дело. Не утверждай, будто знаешь профессию, семью или конкретные планы читателя.
Разные начала, развитие и настроение у разных знаков. Не заполняй выпуск одной схемой
«трудность — разговор — облегчение». Не заставляй все дни отличаться искусственно:
положение медленных планет меняется мало, но формулировки и центральные ситуации не копируй.
Избегай «внутренней ясности», «пространства для манёвра», «опоры», «ресурса», «ситуация прояснится».
Пиши о возможностях и сложностях, а не перечисляй наставления. Один уместный совет допустим.
Каждый знак: один абзац, 3–4 предложения, 25–45 слов, максимум 325 символов с пробелами.
Без времени суток, заголовков, эмодзи внутри абзацев, медицинских и инвестиционных советов.
История содержит только опубликованные тексты: не повторяй их центральную ситуацию и вывод.
Верни JSON с двумя объектами: forecasts (12 знаков -> текст) и basis
(12 знаков -> {body: название использованной планеты из контекста знака,
house: её солнечный дом числом, interpretation: коротко связь символической темы с текстом}).
basis — служебное объяснение, не часть поста. Всегда возвращай все 12 знаков в обоих объектах.
При corrections меняй только перечисленные знаки; остальные оставь дословно.
'''

def validate_basis(result, sky):
    if set(result.get('basis', {})) != set(bot.SIGNS):
        raise ValueError('Нужна основа для всех 12 знаков.')
    for sign, item in result['basis'].items():
        expected = sky['sign_context'][sign]['solar_whole_sign_houses'].get(item.get('body'))
        if not expected or item.get('house') != expected['house'] or not isinstance(item.get('interpretation'), str) or not item['interpretation'].strip():
            raise ValueError(f'{sign}: основа не соответствует расчёту.')

def preview_issues(forecasts, history):
    issues = bot.edition_issues(forecasts, history)
    for sign, text in (forecasts or {}).items():
        if isinstance(text, str) and re.search(r'[A-Za-z]', text):
            issues.setdefault(sign, []).append('Убери иностранные слова: текст целиком на русском.')
    return issues

def run(day):
    # Dedicated namespace: previews never contaminate publication/repetition history.
    def preview_api(method, payload=None, path=None):
        return api(method, payload, path=f'generation-state/astro-preview-v1-{day}.json')
    store = GenerationStore(day, preview_api)
    bot.GENERATION_STORE = store
    bot.API_BUDGET = bot.RequestBudget()
    bot.API_BUDGET.spent, bot.API_BUDGET.calls = store.data['spent'], store.data['calls']
    if store.data.get('result') and not preview_issues(store.data['result']['forecasts'], store.data.get('published_snapshot', [])):
        result = store.data['result']
        sky = store.data['sky']
    else:
        sky = store.data.get('sky') or calculate(day)
        history = store.data.get('published_snapshot')
        if history is None:
            from text_archive import build_archive
            history = build_archive(day, bot.read_history(), [], bot.SIGNS)
        store.data.update(sky=sky, published_snapshot=history)
        store.save()
        key = os.environ['OPENAI_API_KEY'].strip()
        # Reuse the client's existing low-reasoning route only in this isolated process.
        bot.LANGUAGE_PROMPT = PROMPT
        payload = {'sky': sky, 'published_history': history}
        if store.data.get('result'):
            payload.update(previous=store.data['result'], corrections=preview_issues(store.data['result']['forecasts'], history))
        while True:
            result = bot.model_json(key, 'gpt-5.4', PROMPT, payload)
            if 'previous' in payload:
                for sign in bot.SIGNS:
                    if sign not in payload['corrections']:
                        for field in ('forecasts', 'basis'):
                            result[field][sign] = payload['previous'][field][sign]
            validate_basis(result, sky)
            issues = preview_issues(result.get('forecasts'), history)
            if not issues:
                bot.format_edition(day, result['forecasts'])
                break
            payload.update(previous=result, corrections=issues)
        store.data['result'] = result
        store.save()
    folder = Path('astro-preview-output')
    folder.mkdir(exist_ok=True)
    text = bot.format_edition(day, result['forecasts'], markup=False)
    (folder / 'preview.md').write_text(text + '\n\nРазвлекательная астрологическая интерпретация.\n', encoding='utf-8')
    (folder / 'evidence.json').write_text(json.dumps({'sky': sky, 'basis': result['basis'],
        'spent_usd_estimate': bot.API_BUDGET.spent, 'review': 'format and lexical repetition checked; human approval pending'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(text)
    print(f'PREVIEW_ONLY estimated_usd={bot.API_BUDGET.spent:.5f}; nothing published')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True, type=date.fromisoformat)
    run(parser.parse_args().date)
