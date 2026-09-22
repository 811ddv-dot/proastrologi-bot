"""Original one-paragraph forecasts; no recycled fragment fallback."""
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo
from editorial_review import verified_issues, full_source_review

SIGNS = dict(zip('Овен Телец Близнецы Рак Лев Дева Весы Скорпион Стрелец Козерог Водолей Рыбы'.split(), '♈♉♊♋♌♍♎♏♐♑♒♓'))
MONTHS = 'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split()
from editorial import DOMAINS, MOODS, EXAMPLES, PLAN_PROMPT, WRITE_PROMPT, LANGUAGE_PROMPT, QUALITY_PROMPT, ADJUDICATE_PROMPT

STATE = Path('horoscope-state/history.json')
HISTORY_LIMIT = 30
EDITORIAL_ATTEMPTS = 6
TELEGRAM_LIMIT = 4096
MAX_SIGN_LENGTH = 325


def text_length(text):
    # Conservative UTF-16 count also accounts for supplementary-plane emoji.
    return len(text.encode('utf-16-le')) // 2


def read_history():
    if not STATE.exists():
        return []
    history = json.loads(STATE.read_text(encoding='utf-8'))
    if not isinstance(history, list):
        raise ValueError('Повреждена история выпусков.')
    return history[-HISTORY_LIMIT:]


def remember(bundle):
    history = [item for item in read_history() if item['date'] != bundle['date']]
    history.append(bundle)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(history[-HISTORY_LIMIT:], ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(STATE)


def validate_originality(edition, history):
    previous = [body for item in history for body in item['forecasts'].values()]
    for body in edition.values():
        for old in previous:
            if grams(body, 7) & grams(old, 7) or SequenceMatcher(None, words(body), words(old)).ratio() > .60:
                raise ValueError('Прогноз повторяет предыдущий выпуск.')
    for a, b in combinations(edition.values(), 2):
        if SequenceMatcher(None, words(a), words(b)).ratio() > .55:
            raise ValueError('Прогнозы знаков слишком похожи.')


def model_json(key, model, instruction, data):
    for budget in (12000, 24000):
        response = request_json(
            'https://api.openai.com/v1/chat/completions',
            {'model': model, 'messages': [{'role': 'system', 'content': instruction},
                                        {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
             'max_completion_tokens': budget, 'response_format': {'type': 'json_object'},
             **({'reasoning_effort': 'low'} if instruction in (PLAN_PROMPT, QUALITY_PROMPT, LANGUAGE_PROMPT, ADJUDICATE_PROMPT) else {})},
            {'Authorization': f'Bearer {key}'})
        candidate = response['choices'][0]
        usage = response.get('usage')
        if isinstance(usage, dict):
            print('API_USAGE ' + json.dumps({'requested_model': model,
                  'actual_model': response.get('model'), 'usage': usage}),
                  file=sys.stderr, flush=True)
        reason = candidate.get('finish_reason')
        if reason == 'stop':
            return json.loads(candidate['message']['content'])
        if reason != 'length':
            raise ValueError(f'Генерация не завершена: {reason}.')
        print(f'Ответ обрезан при лимите {budget} токенов.', file=sys.stderr, flush=True)
    raise ValueError('Ответ остался обрезанным после одной повторной попытки.')


def words(text):
    return re.findall(r'[а-яё]+', text.lower())


def grams(text, size=5):
    tokens = words(text)
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def validate(edition, require_all=True):
    if not isinstance(edition, dict) or (require_all and set(edition) != set(SIGNS)):
        raise ValueError('Нужны ровно 12 знаков без пропусков.')
    for sign, body in edition.items():
        if not isinstance(body, str) or not 25 <= len(words(body)) <= 55:
            raise ValueError(f'{sign}: нужно 25–55 слов в коротком абзаце.')
        if text_length(body) > MAX_SIGN_LENGTH:
            raise ValueError(f'{sign}: {text_length(body)} символов, сократи до {MAX_SIGN_LENGTH}, не обрывая предложения.')
        sentences = [part for part in re.split(r'[.!?]+', body) if part.strip()]
        if not 3 <= len(sentences) <= 4:
            raise ValueError(f'{sign}: нужно 3–4 предложения.')
        if any(x in body for x in ('\n', '\r', '#', '<', '>', '*')):
            raise ValueError(f'{sign}: нужен один абзац без разметки.')
        if re.search(r'\b(утр(?:о|а|ом|у|ен\w*)|вечер(?:а|ом|у|е|ний|няя|нее|ние)?)\b', body.lower()):
            raise ValueError(f'{sign}: убрать деление по времени суток.')
        if re.search(r'в ближайшие дни|в ближайшее время|пересекутся|сойдутся воедино|профессиональную плоскость|плодотворный цикл', body.lower()):
            raise ValueError(f'{sign}: убрать абстрактный шаблон; нужен конкретный прогноз на один день.')
    for a, b in combinations(edition, 2):
        shared = grams(edition[a]) & grams(edition[b])
        if shared:
            phrase = ' '.join(sorted(shared)[0])
            raise ValueError(f'Повторяющаяся формулировка: {a}, {b}: «{phrase}».')
    patterned = [sign for sign, body in edition.items()
                 if re.search(r'легче всего|сложнее\s*[—–-]', body.lower())]
    if len(patterned) >= 3:
        raise ValueError('Одинаковая композиция «легче всего — сложнее»: ' + ', '.join(patterned)
                         + '. Перепиши без сравнения навыков, с разными началами и развитием.')
    return edition


def clean_labels(edition):
    # Formatting-only cleanup; never changes the substance of a prediction.
    if isinstance(edition, dict):
        return {sign: re.sub(r'\bСовет(?: дня)?:\s*', '', body).strip()
                if isinstance(body, str) else body for sign, body in edition.items()}
    return edition




def request_json(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Never log the request URL: Telegram embeds the secret in it.
        raise RuntimeError(f'Сервис вернул HTTP {exc.code}; проверьте ключ и квоту.') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Сервис не ответил. Автоматический повтор отправки отключён во избежание дублей.') from None


def validate_plan(plan, history):
    if not isinstance(plan, dict) or set(plan) != set(SIGNS):
        raise ValueError('План должен содержать ровно 12 знаков.')
    for sign, item in plan.items():
        if not isinstance(item, dict):
            raise ValueError(f'{sign}: некорректный план.')
        if item.get('domain') not in DOMAINS or item.get('mood') not in MOODS:
            raise ValueError(f'{sign}: неизвестная сфера или настроение.')
        for field in ('situation', 'turn', 'ending'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f'{sign}: нет поля {field}.')
    domains = [item['domain'] for item in plan.values()]
    moods = [item['mood'] for item in plan.values()]
    if len(set(domains)) < 6 or max(domains.count(x) for x in domains) > 3:
        raise ValueError('Недостаточно разных сфер: нужно минимум 6, не больше 3 знаков на сферу.')
    if len(set(moods)) < 3 or max(moods.count(x) for x in moods) > 5:
        raise ValueError('Недостаточно разных настроений: минимум 3, максимум 5 знаков на настроение.')
    def story(item):
        return words(' '.join(item[field] for field in ('situation', 'turn', 'ending')))
    for a, b in combinations(plan, 2):
        if SequenceMatcher(None, story(plan[a]), story(plan[b])).ratio() > .65:
            raise ValueError(f'Повтор сюжета в плане: {a}, {b}.')
    for past in history:
        for sign, item in past.get('plan', {}).items():
            if sign in plan and SequenceMatcher(None, story(plan[sign]), story(item)).ratio() > .65:
                raise ValueError(f'{sign}: план повторяет {past["date"]}.')
    if history:
        for sign, item in history[-1].get('plan', {}).items():
            if sign in plan and plan[sign]['domain'] == item.get('domain'):
                raise ValueError(f'{sign}: смени основную сферу, вчера уже была «{item["domain"]}».')
    return plan


def review_edition(key, model, edition, history, previous=None, previous_issues=None):
    changed = None if previous is None else {sign for sign in SIGNS if edition[sign] != previous[sign]}
    if changed is not None:
        changed.update(previous_issues or {})
    review_history = [{'date': item['date'], 'forecasts': item['forecasts']} for item in history]
    context = {'edition': edition, 'history': review_history,
               'review_signs': list(SIGNS) if changed is None else sorted(changed),
               'previous_issues': previous_issues or {}}
    for attempt in range(2):
        review = model_json(key, model, QUALITY_PROMPT, context)
        try:
            candidates = verified_issues(full_source_review(review, edition, history), edition, history, changed)
            if not candidates:
                return {}
            verdict = model_json(key, model, ADJUDICATE_PROMPT, {'candidates': candidates})
            confirmed = verdict.get('confirmed') if isinstance(verdict, dict) else None
            if (not isinstance(confirmed, list) or any(not isinstance(sign, str) or sign not in candidates
                                                     for sign in confirmed)):
                raise ValueError('Независимая проверка должна вернуть confirmed из предложенных знаков.')
            rejected = sorted(set(candidates) - set(confirmed))
            if rejected:
                print(f'Независимая сверка не подтвердила замечания: {", ".join(rejected)}.', file=sys.stderr, flush=True)
            return {sign: candidates[sign] for sign in confirmed}
        except ValueError as exc:
            context['review_error'] = str(exc)
            context['invalid_review'] = review
            print(f'Проверка доказательств {attempt + 1}/2: {exc}', file=sys.stderr, flush=True)
    raise RuntimeError('Редактор не подтвердил замечания цитатами. Ничего не опубликовано.')


def generate_bundle(day, history):
    key = ''.join(os.environ.get('OPENAI_API_KEY', '').split())
    if not key:
        raise RuntimeError('Добавьте OPENAI_API_KEY в GitHub Actions Secrets.')
    model = os.environ.get('OPENAI_MODEL', 'gpt-5.4')
    if not re.fullmatch(r'[a-zA-Z0-9_./-]+', model):
        raise RuntimeError('Недопустимое имя модели.')
    history = [item for item in history if item['date'] < day.isoformat()][-HISTORY_LIMIT:]
    context = {'date': day.isoformat(), 'signs': list(SIGNS), 'history': history,
               'domains': DOMAINS, 'moods': MOODS}
    for attempt in range(3):
        plan = model_json(key, model, PLAN_PROMPT, context)
        try:
            validate_plan(plan, history)
            break
        except (ValueError, TypeError, KeyError) as exc:
            context['previous_plan'] = plan
            context['validation_error'] = str(exc)
            print(f'План {attempt + 1}/3: {exc}', file=sys.stderr, flush=True)
    else:
        raise RuntimeError('Не удалось подготовить разнообразный план. Ничего не опубликовано.')
    print(f'{day}: план готов; сфер {len(set(x["domain"] for x in plan.values()))}, '
          f'настроений {len(set(x["mood"] for x in plan.values()))}; история {len(history)} дней.',
          file=sys.stderr, flush=True)
    draft = model_json(key, model, WRITE_PROMPT, {
        'date': day.isoformat(), 'plan': plan, 'examples': EXAMPLES, 'history': history})
    editorial_input = {'date': day.isoformat(), 'plan': plan, 'edition': draft,
                       'examples': EXAMPLES, 'history': history}
    repair_signs = None
    feedback_history = []
    reviewed_edition = None
    reviewed_issues = None
    format_attempts = 0
    content_attempts = 0
    for attempt in range(EDITORIAL_ATTEMPTS * 2):
        candidate = clean_labels(model_json(key, model, LANGUAGE_PROMPT, editorial_input))
        if repair_signs is not None and isinstance(candidate, dict) and isinstance(edition, dict):
            edition = {sign: candidate.get(sign, edition.get(sign)) if sign in repair_signs
                       else edition[sign] for sign in SIGNS}
        else:
            edition = candidate
        issues = edition_issues(edition, history)
        if issues:
            format_attempts += 1
        else:
            issues = review_edition(key, model, edition, history, reviewed_edition, reviewed_issues)
            reviewed_edition = dict(edition)
            reviewed_issues = issues
            if issues:
                content_attempts += 1
        if not issues:
            break
        repair_signs = set(issues)
        feedback_history.append(issues)
        editorial_input = {**editorial_input, 'edition': edition,
                           'validation_error': issues, 'quality_feedback': issues,
                           'previous_feedback': feedback_history,
                           'repair_signs': list(issues)}
        print(f'Редактура: содержание {content_attempts}/{EDITORIAL_ATTEMPTS}, '
              f'формат {format_attempts}/{EDITORIAL_ATTEMPTS}: {issues}', file=sys.stderr, flush=True)
        if max(format_attempts, content_attempts) >= EDITORIAL_ATTEMPTS:
            raise RuntimeError('Редактура не прошла проверку. Ничего не опубликовано.')
    else:
        raise RuntimeError('Редактура не прошла проверку. Ничего не опубликовано.')
    print(f'{day}: написание и отдельная языковая редактура завершены.', file=sys.stderr, flush=True)
    return {'date': day.isoformat(), 'plan': plan, 'forecasts': edition}


def validate_language(edition):
    jargon = r'адаптивн|реструктур|структурирован|коммуникаци|взаимодейств|переформат|сфокусирован|ресурс|концепц|интуитивные наработки|эмоциональная составляющая'
    for sign, body in edition.items():
        found = re.search(jargon, body.lower())
        if found:
            raise ValueError(f'{sign}: замени канцеляризм «{found.group()}» естественной фразой.')
        sentences = [x.strip().lower() for x in re.split(r'[.!?]+', body) if x.strip()]
        if len(sentences) != len(set(sentences)):
            raise ValueError(f'{sign}: повтор предложения.')
        for example in EXAMPLES:
            if grams(body, 7) & grams(example, 7):
                raise ValueError(f'{sign}: скопирована фраза из образца; напиши оригинально.')
    return edition


def edition_issues(edition, history):
    if not isinstance(edition, dict) or set(edition) != set(SIGNS):
        return {sign: ['Нужны ровно 12 знаков без пропусков.'] for sign in SIGNS}
    issues = {}
    for sign, body in edition.items():
        try:
            validate({sign: body}, require_all=False)
            validate_language({sign: body})
            validate_originality({sign: body}, history)
        except (ValueError, TypeError, KeyError) as exc:
            issues.setdefault(sign, []).append(str(exc))
    for a, b in combinations(edition, 2):
        if a in issues or b in issues:
            continue
        try:
            validate({a: edition[a], b: edition[b]}, require_all=False)
            validate_originality({a: edition[a], b: edition[b]}, [])
        except ValueError as exc:
            issues.setdefault(b, []).append(str(exc))
    patterned = [sign for sign, body in edition.items() if isinstance(body, str)
                 and re.search(r'легче всего|сложнее\s*[—–-]', body.lower())]
    if len(patterned) >= 3:
        for sign in patterned:
            issues.setdefault(sign, []).append('Убери одинаковую композицию «легче всего — сложнее».')
    return issues


def format_edition(day, edition, markup=True):
    if not isinstance(edition, dict) or set(edition) != set(SIGNS):
        raise ValueError('Для общего поста нужны все 12 знаков.')
    title = f'✨ Гороскоп на {day.day} {MONTHS[day.month - 1]}'
    plain = [title]
    formatted = [f'<b>{title}</b>']
    for sign, icon in SIGNS.items():
        body = edition[sign]
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f'{sign}: пустой текст в общем посте.')
        heading = f'{icon} {sign.upper()}'
        plain.append(f'{heading}\n{body}')
        formatted.append(f'<b>{heading}</b>\n{html.escape(body)}')
    visible = '\n\n'.join(plain)
    if text_length(visible) > TELEGRAM_LIMIT:
        raise ValueError(f'Общий пост: {text_length(visible)} символов, лимит {TELEGRAM_LIMIT}. Ничего не отправлено.')
    return '\n\n'.join(formatted) if markup else visible


def publish_bundle(day, bundle):
    # Validate the entire message before making the single Telegram request.
    post = format_edition(day, bundle['forecasts'])
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Не задан TELEGRAM_BOT_TOKEN.')
    response = request_json(f'https://api.telegram.org/bot{token}/sendMessage',
                            {'chat_id': os.environ.get('TELEGRAM_CHANNEL', '@proastrologi'),
                             'text': post, 'parse_mode': 'HTML'})
    if not response.get('ok'):
        raise RuntimeError('Telegram отклонил общий пост; остановка без повторной отправки.')
    print(f'Отправлен 1 пост, 12 знаков; message_id={response["result"]["message_id"]}', flush=True)
    remember(bundle)


def preview_sequence(day, count):
    # Only an in-memory copy is extended. Publication state is never written here.
    history = [item for item in read_history() if item['date'] < day.isoformat()]
    bundles = []
    sections = ['# Тестовые выпуски\n\nНе отправлены в Telegram. Тексты без ручной редакции.']
    for offset in range(count):
        current = day + timedelta(days=offset)
        bundle = generate_bundle(current, history)
        post_text = format_edition(current, bundle['forecasts'], markup=False)
        post_html = format_edition(current, bundle['forecasts'])
        Path(f'preview-post-{current}.txt').write_text(post_text + '\n', encoding='utf-8')
        Path(f'preview-post-{current}.html').write_text(post_html, encoding='utf-8')
        bundles.append(bundle)
        history = (history + [bundle])[-HISTORY_LIMIT:]
        sections.append(f'## {current.isoformat()}')
        for sign in SIGNS:
            sections.append(f'### {SIGNS[sign]} {sign}\n\n{bundle["forecasts"][sign]}')
        # Checkpoint only completed, validated test days, outside production state.
        Path('preview.md').write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
        Path('preview-data.json').write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Предпросмотр: {current}, 1 пост, 12 знаков, {text_length(post_text)}/{TELEGRAM_LIMIT} символов; '
              f'тестовая история {len(history)} дней.', flush=True)
    Path('preview.md').write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
    Path('preview-data.json').write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = ['# Проверка последовательных выпусков', '', '| Дата | Знак | Сфера | Настроение |',
            '|---|---|---|---|']
    for bundle in bundles:
        for sign, plan in bundle['plan'].items():
            rows.append(f'| {bundle["date"]} | {sign} | {plan["domain"]} | {plan["mood"]} |')
    rows += ['', 'Во всех выпусках проверены состав знаков, длина, абзацы, повторяющиеся фразы, '
             'сходство с предыдущими выпусками, заданные канцеляризмы и копирование образцов. '
             'Проверка слов не является гарантией смысловой уникальности; смысл учитывается планировщиком и редактором.']
    Path('preview-report.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    print('\n\n'.join(sections), flush=True)
    return bundles


def next_edition_date(now=None):
    """Evening publication always targets the next Moscow calendar day."""
    now = now or datetime.now(ZoneInfo('Europe/Moscow'))
    return now.astimezone(ZoneInfo('Europe/Moscow')).date() + timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Показать выпуск без отправки в Telegram')
    parser.add_argument('--tomorrow', action='store_true', help='Вечерний выпуск на следующий день по Москве')
    parser.add_argument('--date', type=date.fromisoformat, help='Дата только для предпросмотра')
    parser.add_argument('--preview-days', type=int, default=1, choices=range(1, 4),
                        help='От 1 до 3 последовательных тестовых дней; без записи истории публикаций')
    args = parser.parse_args()
    if args.date and not args.preview:
        parser.error('--date разрешён только вместе с --preview')
    if args.preview_days != 1 and not args.preview:
        parser.error('--preview-days разрешён только вместе с --preview')
    day = args.date or (next_edition_date() if args.tomorrow else datetime.now(ZoneInfo('Europe/Moscow')).date())
    if args.preview:
        preview_sequence(day, args.preview_days)
        return
    if not args.preview and any(item['date'] == day.isoformat() for item in read_history()):
        print('Выпуск на эту дату уже отправлен. Повтор пропущен.')
        return
    bundle = generate_bundle(day, read_history())
    publish_bundle(day, bundle)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        sys.exit(1)
