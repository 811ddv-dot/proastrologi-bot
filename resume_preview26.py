"""Resume four rejected signs from the fixed saved September 26 preview; never publish."""
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import daily_horoscope as bot
from editorial_review import full_source_review, verified_issues

DAY = date(2026, 9, 26)
TARGETS = {'Овен', 'Козерог', 'Водолей', 'Рыбы'}
BASE_KEYS = (
    '934e899c1da3d259dce9fcce265ab5f14bca4f570691467191b7a331de1993e9',
    '0f8c83bc7469417e812f5af1948c6f98bedda1ad4ee58fbbfca7a338794560c3',
    '8f55b010956d84bd37628e056e95244057cc2fbb6cafaa18ba0cb2c19715f4c2',
)
REVIEW_KEY = 'a642406d29d412e74255ced1d69987c8b6d76f24df7603921e73b702dcb92f62'


def write_preview(bundle):
    plain = bot.format_edition(DAY, bundle['forecasts'], markup=False)
    Path('preview.md').write_text('# Предпросмотр — не опубликован\n\n' + plain, encoding='utf-8')
    Path('preview-data.json').write_text(json.dumps([bundle], ensure_ascii=False, indent=2), encoding='utf-8')
    Path(f'preview-post-{DAY}.txt').write_text(plain, encoding='utf-8')
    Path(f'preview-post-{DAY}.html').write_text(bot.format_edition(DAY, bundle['forecasts']), encoding='utf-8')
    print(plain, flush=True)
    print(f'TOTAL_PREVIEW_COST estimated_usd={bot.API_BUDGET.spent:.5f}/1.00', flush=True)


def run():
    if datetime.now(ZoneInfo('Europe/Moscow')).date() != date(2026, 9, 23):
        raise RuntimeError('Срок одноразового разрешения истёк.')
    bot.open_generation_store(DAY)
    store = bot.GENERATION_STORE
    if store is None or store.data.get('pending'):
        raise RuntimeError('Нет безопасного журнала для продолжения.')
    if store.data.get('approved_preview'):
        write_preview(store.data['approved_preview'])
        return
    if store.data.get('repair26_finished'):
        raise RuntimeError('Разрешённая доработка уже завершена; повтор не запускается.')
    history = store.data['repeat_history']
    original = {}
    for key in BASE_KEYS:
        original.update(store.data['responses'][key])
    if set(original) != set(bot.SIGNS):
        raise RuntimeError('Не восстановлен полный исходный выпуск.')
    review = store.data['responses'][REVIEW_KEY]
    issues = verified_issues(full_source_review(review, original, history), original, history)
    issues = {sign: notes for sign, notes in issues.items() if sign in TARGETS}
    if set(issues) != TARGETS:
        raise RuntimeError('Исходные замечания не совпадают с согласованными знаками.')
    bot.API_BUDGET.limit, bot.API_BUDGET.max_calls = 1.0, 18
    key = ''.join(os.environ.get('OPENAI_API_KEY', '').split())
    if not key:
        raise RuntimeError('Нет API-ключа.')
    edition = dict(original)
    feedback = []
    for attempt in range(2):
        targets = set(issues)
        payload = bot.repair_payload(DAY, {}, edition, issues, feedback, history)
        patch = bot.clean_labels(bot.model_json(key, 'gpt-5.4', bot.REPAIR_PROMPT, payload))
        if not isinstance(patch, dict) or set(patch) != targets:
            raise ValueError('Правка должна содержать только проблемные знаки.')
        candidate = {sign: patch[sign] if sign in targets else edition[sign] for sign in bot.SIGNS}
        feedback.append(issues)
        issues = bot.edition_issues(candidate, history)
        if not issues:
            issues = bot.review_edition(key, 'gpt-5.4', candidate, history, edition,
                                       {sign: [] for sign in targets})
        edition = candidate
        if not issues:
            if any(edition[s] != original[s] for s in set(bot.SIGNS) - TARGETS):
                raise RuntimeError('Изменился замороженный знак.')
            bundle = {'date': str(DAY), 'forecasts': edition}
            bot.format_edition(DAY, edition)
            store.data['approved_preview'] = bundle
            store.data['repair26_finished'] = True
            store.save()
            write_preview(bundle)
            return
        if not set(issues) <= TARGETS:
            raise RuntimeError('Замечания вне согласованных четырёх знаков.')
        print(f'REPAIR26 {attempt + 1}: {json.dumps(issues, ensure_ascii=False)}', flush=True)
    store.data['repair26_finished'] = True
    store.save()
    raise RuntimeError('Доработка не прошла проверку; тексты сохранены, публикации нет.')
