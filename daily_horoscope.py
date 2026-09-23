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
from editorial import REPAIR_PROMPT

STATE = Path('horoscope-state/history.json')
HISTORY_LIMIT = 30
EDITORIAL_ATTEMPTS = 2
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


class RequestBudget:
    """Conservative USD estimate, shared by all preview days in this process.

    With durable generation enabled, also restored for the target edition.
    Not an account billing limit. Rates: OpenAI standard text, 2026-09-22.
    Reserve before network IO; ambiguous failures retain the full reservation.
    """
    def __init__(self):
        self.calls = 0
        self.spent = 0.0
        self.limit = .50
        self.max_calls = 8

    def reserve(self, model, messages, output):
        if model not in ('gpt-5.4', 'gpt-5-mini'):
            raise RuntimeError('Для этой модели не настроена защита расходов.')
        # UTF-8 byte bound plus ample framing overhead for text-only messages.
        inputs = sum(len(m['content'].encode('utf-8')) + 100 for m in messages) + 1000
        if inputs > 270000:
            raise RuntimeError('Контекст слишком велик для безопасного бюджета.')
        # Use GPT-5.4 rates conservatively for either allowed model.
        amount = (inputs * 2.5 + output * 15) / 1000000
        if self.calls >= self.max_calls or self.spent + amount > self.limit:
            raise RuntimeError(f'Лимит запуска: {self.max_calls} API-запросов или ${self.limit:.2f} расчётного бюджета. Повторные запросы остановлены.')
        self.calls += 1
        self.spent += amount
        return amount

    def settle(self, reserved, usage):
        if isinstance(usage, dict):
            values = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
            if all(type(n) is int and n >= 0 for n in values):
                actual = (values[0] * 2.5 + values[1] * 15) / 1000000
                self.spent += actual - reserved
        print(f'API_BUDGET calls={self.calls}/{self.max_calls} estimated_usd={self.spent:.5f}/{self.limit:.2f}', file=sys.stderr, flush=True)


API_BUDGET = RequestBudget()
GENERATION_STORE = None


def open_generation_store(day):
    """Opt-in until the new version has been approved for production."""
    global GENERATION_STORE
    GENERATION_STORE = None
    if os.environ.get('DURABLE_GENERATION') != 'true':
        return
    from generation_store import GenerationStore
    from history_store import api
    GENERATION_STORE = GenerationStore(day, api)
    API_BUDGET.calls = max(API_BUDGET.calls, GENERATION_STORE.data['calls'])
    API_BUDGET.spent = max(API_BUDGET.spent, GENERATION_STORE.data['spent'])


def model_json(key, model, instruction, data):
    for budget in (6000,):
        messages = [{'role': 'system', 'content': instruction},
                    {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]
        from generation_store import fingerprint
        cache_key = fingerprint({'model': model, 'instruction': instruction, 'data': data,
                                 'output_limit': budget, 'pipeline_version': 1})
        if GENERATION_STORE is not None:
            hit, result = GENERATION_STORE.cached(cache_key)
            if hit:
                print('CHECKPOINT: использован сохранённый ответ, без API-запроса.', flush=True)
                return result
        reserved = API_BUDGET.reserve(model, messages, budget)
        if GENERATION_STORE is not None:
            GENERATION_STORE.begin(cache_key, API_BUDGET)
        response = request_json(
            'https://api.openai.com/v1/chat/completions',
            {'model': model, 'messages': messages, 'service_tier': 'default',
             'max_completion_tokens': budget, 'response_format': {'type': 'json_object'},
             **({'reasoning_effort': 'low'} if instruction in (PLAN_PROMPT, QUALITY_PROMPT, LANGUAGE_PROMPT, ADJUDICATE_PROMPT, REPAIR_PROMPT) else {})},
            {'Authorization': f'Bearer {key}'})
        candidate = response['choices'][0]
        usage = response.get('usage')
        API_BUDGET.settle(reserved, usage)
        if isinstance(usage, dict):
            print('API_USAGE ' + json.dumps({'requested_model': model,
                  'actual_model': response.get('model'), 'usage': usage}),
                  file=sys.stderr, flush=True)
        reason = candidate.get('finish_reason')
        if reason == 'stop':
            result = json.loads(candidate['message']['content'])
            if GENERATION_STORE is not None:
                GENERATION_STORE.finish(cache_key, result, API_BUDGET)
            return result
        if reason != 'length':
            raise ValueError(f'Генерация не завершена: {reason}.')
        print(f'Ответ обрезан при лимите {budget} токенов.', file=sys.stderr, flush=True)
    raise ValueError('Ответ обрезан. Автоматический платный повтор отключён.')


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
        with urllib.request.urlopen(req, timeout=300 if url.startswith('https://api.openai.com/') else 120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Never log the request URL: Telegram embeds the secret in it.
        raise RuntimeError(f'Сервис вернул HTTP {exc.code}; проверьте ключ и квоту.') from None
    except (urllib.error.URLError, TimeoutError):
        service = 'OpenAI' if url.startswith('https://api.openai.com/') else 'Telegram'
        raise RuntimeError(f'{service} не ответил. Результат запроса неизвестен; автоматический повтор отключён.') from None


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


def repair_payload(day, plan, edition, issues, feedback_history, history=None):
    """Only repair targets and cited conflicts; full history stays in validators."""
    targets = [sign for sign in SIGNS if sign in issues]
    replace_story = [sign for sign in targets if any(
        (isinstance(item, dict) and item.get('kind') == 'duplicate')
        or (isinstance(item, str) and 'повтор' in item.lower()) for item in issues[sign])]
    feedback = {}
    for sign in targets:
        feedback[sign] = []
        for item in issues[sign]:
            if isinstance(item, dict):
                # Current quote duplicates edition[sign]; reference is the conflict.
                feedback[sign].append({k: item[k] for k in ('kind', 'reason', 'reference') if k in item})
            else:
                feedback[sign].append(item)
    previous = {}
    for sign in targets:
        notes = []
        for old in feedback_history[-2:]:
            for item in old.get(sign, []):
                note = item.get('reason', '') if isinstance(item, dict) else str(item)
                if note and note not in notes:
                    notes.append(note)
        if notes:
            previous[sign] = notes
    payload = {'date': day.isoformat(), 'repair_signs': targets,
            'plan': {sign: plan[sign] for sign in targets if sign not in replace_story and sign in plan},
            'edition': {sign: edition.get(sign) for sign in targets if sign not in replace_story},
            'replace_story': replace_story,
            'rejected_texts': {sign: edition.get(sign) for sign in replace_story},
            'quality_feedback': feedback, 'previous_feedback': previous}
    if history is not None:
        from text_archive import INSTRUCTION
        payload['originality_instruction'] = INSTRUCTION
        payload['history'] = [{'date': item['date'], 'forecasts': item['forecasts']} for item in history]
        payload['other_signs'] = {sign: body for sign, body in edition.items() if sign not in targets}
        payload['repair_instruction'] = ('Проверь всю историю и остальные знаки: нельзя заменить '
            'один старый сюжет другим старым. Сохрани общий жанр прогноза, но измени '
            'саму центральную тенденцию повторяющегося текста, а не слова.')
    return payload


def generate_bundle(day, history):
    key = ''.join(os.environ.get('OPENAI_API_KEY', '').split())
    if not key:
        raise RuntimeError('Добавьте OPENAI_API_KEY в GitHub Actions Secrets.')
    model = os.environ.get('OPENAI_MODEL', 'gpt-5.4')
    if not re.fullmatch(r'[a-zA-Z0-9_./-]+', model):
        raise RuntimeError('Недопустимое имя модели.')
    history = [item for item in history if item['date'] < day.isoformat()][-HISTORY_LIMIT:]
    from text_archive import history_for_generation, INSTRUCTION
    published_history = history
    history = history_for_generation(day, history, GENERATION_STORE, SIGNS)
    context = {'date': day.isoformat(), 'signs': list(SIGNS), 'history': history,
               'originality_instruction': INSTRUCTION,
               'domains': DOMAINS, 'moods': MOODS}
    for attempt in range(3):
        plan = model_json(key, model, PLAN_PROMPT, context)
        try:
            validate_plan(plan, published_history)
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
        'date': day.isoformat(), 'plan': plan, 'examples': EXAMPLES, 'history': history,
        'originality_instruction': INSTRUCTION})
    editorial_input = {'date': day.isoformat(), 'plan': plan, 'edition': draft,
                       'examples': EXAMPLES, 'history': history,
                       'originality_instruction': INSTRUCTION}
    repair_signs = None
    feedback_history = []
    reviewed_edition = None
    reviewed_issues = None
    format_attempts = 0
    content_attempts = 0
    replanned = False
    for attempt in range(EDITORIAL_ATTEMPTS * 2):
        candidate = clean_labels(model_json(key, model,
            REPAIR_PROMPT if repair_signs is not None else LANGUAGE_PROMPT, editorial_input))
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
        editorial_input = repair_payload(day, plan, edition, issues, feedback_history, history)
        replanned = replanned or bool(editorial_input['replace_story'])
        feedback_history.append(issues)
        print(f'Редактура: содержание {content_attempts}/{EDITORIAL_ATTEMPTS}, '
              f'формат {format_attempts}/{EDITORIAL_ATTEMPTS}: {issues}', file=sys.stderr, flush=True)
        if max(format_attempts, content_attempts) >= EDITORIAL_ATTEMPTS:
            raise RuntimeError('Редактура не прошла проверку. Ничего не опубликовано.')
    else:
        raise RuntimeError('Редактура не прошла проверку. Ничего не опубликовано.')
    print(f'{day}: написание и отдельная языковая редактура завершены.', file=sys.stderr, flush=True)
    # A superseded plan must never be saved as the plan of the final text.
    return {'date': day.isoformat(), 'forecasts': edition, **({} if replanned else {'plan': plan})}


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
    if GENERATION_STORE is not None and not GENERATION_STORE.begin_delivery(bundle):
        remember(bundle)
        print('Публикация уже подтверждена Telegram; восстановлена только история.', flush=True)
        return
    response = request_json(f'https://api.telegram.org/bot{token}/sendMessage',
                            {'chat_id': os.environ.get('TELEGRAM_CHANNEL', '@proastrologi'),
                             'text': post, 'parse_mode': 'HTML'})
    if not response.get('ok'):
        raise RuntimeError('Telegram отклонил общий пост; остановка без повторной отправки.')
    if GENERATION_STORE is not None:
        GENERATION_STORE.finish_delivery(response['result']['message_id'])
    print(f'Отправлен 1 пост, 12 знаков; message_id={response["result"]["message_id"]}', flush=True)
    remember(bundle)


def preview_sequence(day, count):
    # Only an in-memory copy is extended. Publication state is never written here.
    history = [item for item in read_history() if item['date'] < day.isoformat()]
    bundles = []
    sections = ['# Тестовые выпуски\n\nНе отправлены в Telegram. Тексты без ручной редакции.']
    for offset in range(count):
        current = day + timedelta(days=offset)
        open_generation_store(current)
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
        for sign, plan in bundle.get('plan', {}).items():
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


def authorize_preview_budget(day, count, preview, now=None):
    """Owner-approved $1 TOTAL continuation, only this edition and authorization day."""
    now = now or datetime.now(ZoneInfo('Europe/Moscow'))
    if (preview and count == 1 and day == date(2026, 9, 26)
            and now.astimezone(ZoneInfo('Europe/Moscow')).date() == date(2026, 9, 23)):
        API_BUDGET.limit = 1.0
        API_BUDGET.max_calls = 12
        # open_generation_store subsequently restores ALL earlier costs and calls.


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
        authorize_preview_budget(day, args.preview_days, args.preview)
        if day == date(2026, 9, 26) and args.preview_days == 1:
            from resume_preview26 import run
            run()
            return
        preview_sequence(day, args.preview_days)
        return
    if not args.preview and any(item['date'] == day.isoformat() for item in read_history()):
        print('Выпуск на эту дату уже отправлен. Повтор пропущен.')
        return
    open_generation_store(day)
    if GENERATION_STORE is not None and GENERATION_STORE.data.get('delivery'):
        delivery = GENERATION_STORE.data['delivery']
        if delivery.get('status') != 'sent':
            raise RuntimeError('Результат предыдущей отправки неизвестен. '
                               'Генерация и повторная отправка заблокированы до проверки.')
        bundle = delivery['bundle']
        if bundle['date'] != day.isoformat():
            raise RuntimeError('Дата сохранённой публикации не совпадает.')
        remember(bundle)
        print('Восстановлена история подтверждённой публикации, без генерации и отправки.')
        return
    bundle = generate_bundle(day, read_history())
    publish_bundle(day, bundle)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        sys.exit(1)
