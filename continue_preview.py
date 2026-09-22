"""One owner-authorized continuation, September 24; never sends to Telegram."""
import base64
import json
import os
from datetime import date
from pathlib import Path

import daily_horoscope as bot
import history_store
from generation_store import GenerationStore

DAY = date(2026, 9, 24)
SOURCE_SHA = '2bf95bcdea96201a9b13d1591603305743473c87'
SOURCE_KEYS = (
    '5eedc74d3f86e75d8a0296803757ef4d8c372fd7d100f8d00095aa4096b53908',
    '74af01e07b211492bfa2e7c8b049079f8b541e942a29a2c72aa15c78d9b135e5',
    '7f41d94047147c50ab84cb40ef2eac0d9327846c3421b395f6013b7e7f054922',
    '238c8ca809f8f1355b48c539875a8316c072b04808f56c6a0a6ce5c4f0b573a5',
)
TARGETS = {'Овен', 'Рак'}


def load_source():
    remote = history_store.api('GET', path='generation-state/2026-09-24.json')
    if not remote or remote['sha'] != SOURCE_SHA:
        raise RuntimeError('Исходный журнал изменился; продолжение остановлено.')
    source = json.loads(base64.b64decode(remote['content']))
    if source['pending'] or source['calls'] != 8:
        raise RuntimeError('Исходная генерация не завершена.')
    responses = source['responses']
    plan, edition, patch, review = [responses[key] for key in SOURCE_KEYS]
    edition = {**edition, **patch}
    return source, plan, edition, review


def continuation_api(method, payload=None, path=None):
    # Separate fixed journal: repeat execution cannot replenish the approved $0.50.
    return history_store.api(method, payload, path='generation-state/2026-09-24-continuation-1.json')


def merge_targets(edition, patch, targets):
    if not isinstance(patch, dict) or set(patch) != set(targets):
        raise ValueError('Правка должна содержать только запрошенные знаки.')
    return {sign: patch[sign] if sign in targets else edition[sign] for sign in bot.SIGNS}


def run():
    source, plan, original, review = load_source()
    history = [x for x in bot.read_history() if x['date'] < DAY.isoformat()][-30:]
    if not history:
        raise RuntimeError('Нет истории; продолжение остановлено.')
    key = ''.join(os.environ.get('OPENAI_API_KEY', '').split())
    if not key:
        raise RuntimeError('Нет API-ключа.')
    bot.GENERATION_STORE = GenerationStore(DAY, continuation_api)
    bot.API_BUDGET = bot.RequestBudget()
    bot.API_BUDGET.calls = bot.GENERATION_STORE.data['calls']
    bot.API_BUDGET.spent = bot.GENERATION_STORE.data['spent']
    edition = dict(original)
    feedback = {s: review['issues'][s] for s in TARGETS}
    targets = set(TARGETS)
    for attempt in range(3):
        patch = bot.model_json(key, 'gpt-5.4', bot.LANGUAGE_PROMPT, {
            'date': str(DAY), 'repair_signs': sorted(targets),
            'edition': edition, 'plan': {s: plan[s] for s in targets},
            'history': history, 'quality_feedback': feedback,
            'repair_instruction': 'Верни JSON только для repair_signs. Остальные тексты неизменны. '
                'Проверь ВСЮ историю: нельзя заменить один старый сюжет другим старым. '
                'Для Овна избегай сюжетов о внезапном понимании учебного материала, '
                'пробелах в знаниях, вопросе, который проясняет тему. '
                'Для Рака избегай сюжетов об отдыхе через отсутствие требований, '
                'снятии раздражения и постепенном расслаблении. '
                'Нужна иная центральная тенденция в заданной сфере; не синонимы. '
                'Верни готовые абзацы без пояснений и без сюжетов других знаков.'})
        candidate = merge_targets(edition, bot.clean_labels(patch), targets)
        issues = bot.edition_issues(candidate, history)
        if not issues:
            issues = bot.review_edition(key, 'gpt-5.4', candidate, history, edition,
                                        {s: [] for s in targets})
        edition = candidate
        if not issues:
            break
        if not set(issues) <= TARGETS:
            raise RuntimeError('Замечание за пределами двух согласованных знаков; остановка.')
        targets, feedback = set(issues), issues
        print(f'Продолжение {attempt + 1}: замечания {json.dumps(issues, ensure_ascii=False)}', flush=True)
    else:
        raise RuntimeError('Повторы не устранены; новые попытки не запускаются.')
    for sign in set(bot.SIGNS) - TARGETS:
        if edition[sign] != original[sign]:
            raise RuntimeError('Изменился согласованный текст другого знака.')
    bundle = {'date': str(DAY), 'plan': plan, 'forecasts': edition}
    plain = bot.format_edition(DAY, edition, markup=False)
    Path('preview.md').write_text('# Предпросмотр — не опубликован\n\n' + plain, encoding='utf-8')
    Path('preview-data.json').write_text(json.dumps([bundle], ensure_ascii=False, indent=2), encoding='utf-8')
    Path(f'preview-post-{DAY}.txt').write_text(plain, encoding='utf-8')
    Path(f'preview-post-{DAY}.html').write_text(bot.format_edition(DAY, edition), encoding='utf-8')
    print(plain, flush=True)
    print(f'COST original_estimate={source["spent"]:.5f} additional_estimate={bot.API_BUDGET.spent:.5f} '
          f'total_estimate={source["spent"] + bot.API_BUDGET.spent:.5f}', flush=True)


if __name__ == '__main__':
    run()
