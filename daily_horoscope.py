"""Original one-paragraph forecasts; no recycled fragment fallback."""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

SIGNS = dict(zip('Овен Телец Близнецы Рак Лев Дева Весы Скорпион Стрелец Козерог Водолей Рыбы'.split(), '♈♉♊♋♌♍♎♏♐♑♒♓'))
MONTHS = 'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split()
PROMPT = '''Ты автор оригинального развлекательного ежедневного гороскопа.
Напиши общий прогноз для каждого из 12 знаков на переданную дату.
Формат: один абзац, 65–95 слов, 4–6 предложений на знак, обращение на «вы».

Главное — связная мысль и различие содержания, а не украшения.
Дай каждому знаку собственный характер дня и центральную тему. Развивай её:
какие обстоятельства вероятны и как они могут изменить дела или общение.
Не сравнивай в каждом тексте, что даётся легче, а что сложнее. Нужен прогноз, не оценка навыков.
Допустим один уместный совет, не цепочка наставлений.
В выпуске должны быть разные настроения: благоприятное, сдержанное, неоднозначное.
Не закрепляй настроение или жизненную сферу за знаком навсегда.

Это общий прогноз, НЕ рассказ о заранее известных действиях читателя.
Не выдумывай точные звонки, найденные предметы, поломки, транспорт, еду, места встреч.
Предпочитай узнаваемые ситуации без реквизита: изменение договорённостей, разница
в ожиданиях, возможность проявить себя, пересмотр отношения к человеку.
Не вставляй эти примеры по очереди; находи собственные разные темы.
Не обещай, что событие обязательно случится. Не начинай каждое предложение с «возможно».
Пиши живым грамотным русским, без делового жаргона, туманных метафор и психотерапевтических лозунгов.
Не заполняй объём словами «небольшой», «простой», «полезный», «ясность» и оптимистичной моралью.
Не обязан давать совет: предпочтительнее описать, как могут сложиться обстоятельства.
Хотя бы половина абзацев должна обходиться без повелительных форм и наставлений.
Не используй фразы «тема дня», «совет:», «личные границы», «перераспределение обязанностей».
Не делай весь выпуск про согласование условий, рабочую нагрузку и реализацию идей.
Различай сюжеты на уровне человеческих переживаний и обстоятельств, а не названий сфер.
Не соединяй несвязанные события в одном абзаце и не делай все концовки одинаковыми.
Избегай «концептуальные предложения», «генерация концепций», «ситуационные проекты»,
«тактическое преимущество», «устойчивая система», «измеримый план»: это не деловой отчёт.
Ориентир качества языка (не копируй эти фразы и сюжеты):
«Не всё получится решить с первой попытки, однако день может оказаться удачнее,
чем покажется поначалу. Поддержка вероятна со стороны человека, с которым вы редко
совпадаете во мнениях. Зато в привычных делах лучше полагаться на собственный опыт:
чужие подсказки сейчас могут только запутать».
«Поводов для волнения будет меньше, чем вы ожидаете. Разногласия, которые казались
серьёзными, отступят, когда появится общая цель. Не исключены приятные новости от тех,
с кем вы давно не общались. День оставит ощущение, что многое наконец встаёт на свои места».
Это образцы интонации, НЕ готовые прогнозы. Не делай все тексты похожими на них.
Характер знака может влиять на реакцию, но не подменяет прогноз описанием личности.

Переданная история — только материал для сравнения, не пример для подражания.
Не повторяй смысловую связку «ситуация — развитие — совет» из истории или другого знака.
Общая сфера вроде работы может совпасть; центральная мысль и поворот должны различаться.
Не копируй и не пересказывай чужие гороскопы. Не заявляй о расчёте планет.
Без утра и вечера, рубрик, списков, разметки, эмодзи внутри текста.
Без медицинских/инвестиционных советов, запугивания и обещаний дохода.
Верни только JSON: 12 русских названий знаков — тексты.
'''

REVIEW_PROMPT = '''Ты независимый выпускающий редактор. Оцени готовый выпуск по требованиям.
Сравни ВСЕ пары знаков и каждый текст с историей: разные слова не устраняют одинаковый смысл.
Отклоняй конкретные дефекты:
1. Повтор центральной ситуации, её развития и вывода у разных знаков или в истории.
2. Перечень несвязанных бытовых происшествий, выдуманные точные действия/предметы вместо общего прогноза.
3. Одинаковое настроение и композиция большинства текстов; советы вместо прогноза.
4. Неестественные фразы, канцелярит или пустая мораль.
Не отклоняй только за общую сферу (работа, отношения) или общие служебные слова.
Близкие советы сами по себе НЕ дубль: для смыслового повтора должны совпасть одновременно
центральная ситуация, её развитие и вывод. Разные причины и последствия общения — разные сюжеты.
Отмечай только существенные дефекты, а не необязательные стилистические предпочтения.
Не требуй литературного совершенства. Для каждого дефекта укажи знак, короткую цитату
и конкретную инструкцию исправления; для повтора также сравниваемый знак/дату.
Предлагай простые человеческие ситуации, не бизнес-процессы, роли модератора,
реструктуризацию, масштабирование или форматы отчётности. Не вводи новые требования.
Верни JSON {"issues": [{"sign": "Овен", "evidence": "цитата и сопоставление", "fix": "что изменить"}]}.
Поле sign содержит ровно один ключ из edition, в именительном падеже. Для нескольких знаков
создай отдельные замечания. Не используй «все знаки», «Девы», «Козероги» или объединённые названия.
Если конкретных дефектов нет, верни {"issues": []}. Не переписывай тексты.
'''

STATE = Path('horoscope-state/history.json')


def read_history():
    if not STATE.exists():
        return []
    history = json.loads(STATE.read_text(encoding='utf-8'))
    if not isinstance(history, list):
        raise ValueError('Повреждена история выпусков.')
    return history[-7:]


def remember(day, edition):
    history = [item for item in read_history() if item['date'] != day.isoformat()]
    history.append({'date': day.isoformat(), 'forecasts': edition})
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(history[-7:], ensure_ascii=False, indent=2), encoding='utf-8')
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
    response = request_json(
        'https://api.openai.com/v1/chat/completions',
        {'model': model, 'messages': [{'role': 'system', 'content': instruction},
                                    {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
         'max_completion_tokens': 12000, 'response_format': {'type': 'json_object'}},
        {'Authorization': f'Bearer {key}'})
    candidate = response['choices'][0]
    if candidate.get('finish_reason') != 'stop':
        raise ValueError('Генерация не завершена.')
    return json.loads(candidate['message']['content'])


def words(text):
    return re.findall(r'[а-яё]+', text.lower())


def grams(text, size=5):
    tokens = words(text)
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def validate(edition):
    if not isinstance(edition, dict) or set(edition) != set(SIGNS):
        raise ValueError('Нужны ровно 12 знаков без пропусков.')
    for sign, body in edition.items():
        if not isinstance(body, str) or not 45 <= len(words(body)) <= 110:
            raise ValueError(f'{sign}: неподходящая длина прогноза.')
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


def review_issues(review):
    if not isinstance(review, dict) or not isinstance(review.get('issues'), list):
        raise ValueError('Редактор не вернул список замечаний.')
    issues = review['issues']
    for issue in issues:
        if (not isinstance(issue, dict) or issue.get('sign') not in SIGNS
                or not isinstance(issue.get('evidence'), str) or not issue['evidence'].strip()
                or not isinstance(issue.get('fix'), str) or not issue['fix'].strip()):
            raise ValueError('Некорректное замечание редактора.')
    return issues


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


def generate(day):
    # Some browser password managers copy a displayed key with line breaks.
    # API keys never contain whitespace, so normalize it before building the header.
    key = ''.join(os.environ.get('OPENAI_API_KEY', '').split())
    if not key:
        raise RuntimeError('Добавьте OPENAI_API_KEY в GitHub Actions Secrets. Старые тексты повторно не публикуются.')
    model = os.environ.get('OPENAI_MODEL', 'gpt-5-mini')
    if not re.fullmatch(r'[a-zA-Z0-9_./-]+', model):
        raise RuntimeError('Недопустимое имя модели.')
    history = [item for item in read_history() if item['date'] < day.isoformat()]
    feedback = []
    edition = None
    semantic_review_done = False
    for attempt in range(4):
        try:
            if edition is None:
                edition = model_json(key, model, PROMPT, {
                    'date': day.isoformat(), 'signs': list(SIGNS), 'history': history,
                    'editor_feedback': feedback})
            else:
                targets = list(dict.fromkeys(item['sign'] for item in feedback))
                patches = model_json(key, model, PROMPT + '\nИсправь только знаки из repair_signs. '
                    'Остальные тексты приведены для сравнения, их не возвращай. '
                    'Верни JSON: только исправляемые знаки — новые абзацы.', {
                        'date': day.isoformat(), 'edition': edition, 'history': history,
                        'repair_signs': targets, 'editor_feedback': feedback})
                if not isinstance(patches, dict) or set(patches) != set(targets):
                    raise ValueError('Неполный набор исправленных знаков.')
                edition = {**edition, **patches}
            edition = clean_labels(edition)
            format_issues = []
            try:
                validate(edition)
                validate_originality(edition, history)
            except ValueError as exc:
                format_issues = [{'sign': sign, 'evidence': str(exc),
                                  'fix': 'Исправь указанное нарушение; хорошие части оставь.'}
                                 for sign in SIGNS if sign in str(exc)]
                if not format_issues:
                    format_issues = [{'sign': sign, 'evidence': str(exc),
                                      'fix': 'Устрани нарушение формата или повтор.'} for sign in SIGNS]
            feedback = []
            if not semantic_review_done:
                review_data = {'requirements': PROMPT, 'date': day.isoformat(), 'edition': edition, 'history': history}
                review = model_json(key, model, REVIEW_PROMPT, review_data)
                try:
                    feedback = review_issues(review)
                except ValueError:
                    # Retry the review schema, not the already-written edition.
                    review_data['invalid_review'] = review
                    review_data['repair_request'] = 'Исправь только JSON замечаний: sign обязан точно совпадать с ключом edition.'
                    feedback = review_issues(model_json(key, model, REVIEW_PROMPT, review_data))
                semantic_review_done = True
            feedback.extend(format_issues)
            if not feedback:
                print('Смысловая редактура завершена; формат и буквальные повторы проверены.', file=sys.stderr, flush=True)
                return edition
            print(f'Редактор {attempt + 1}/4: ' + json.dumps(feedback, ensure_ascii=False),
                  file=sys.stderr, flush=True)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            print(f'Проверка {attempt + 1}/4: {exc}', file=sys.stderr, flush=True)
            feedback = [{'sign': sign, 'evidence': str(exc), 'fix': 'Исправь нарушение формата или повтор.'}
                        for sign in SIGNS]
            if not isinstance(edition, dict) or set(edition) != set(SIGNS):
                edition = None
                semantic_review_done = False
    raise RuntimeError('Выпуск не прошёл проверку после четырёх попыток. Ничего не опубликовано.')


def format_post(day, sign, body):
    return f'<b>{SIGNS[sign]} {sign.upper()} — {day.day} {MONTHS[day.month - 1]}</b>\n\n{html.escape(body)}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Показать выпуск без отправки в Telegram')
    parser.add_argument('--date', type=date.fromisoformat, help='Дата только для предпросмотра')
    parser.add_argument('--remember-preview', action='store_true', help='Сохранить предпросмотр в отдельную тестовую историю')
    args = parser.parse_args()
    if args.date and not args.preview:
        parser.error('--date разрешён только вместе с --preview')
    day = args.date or datetime.now(ZoneInfo('Europe/Moscow')).date()
    if not args.preview and any(item['date'] == day.isoformat() for item in read_history()):
        print('Выпуск на эту дату уже отправлен. Повтор пропущен.')
        return
    edition = generate(day)  # Validate all 12 before sending even the first post.
    posts = [format_post(day, sign, edition[sign]) for sign in SIGNS]
    if args.preview:
        Path('preview.md').write_text('\n\n'.join(post.replace('<b>', '**').replace('</b>', '**') for post in posts), encoding='utf-8')
        if args.remember_preview:
            remember(day, edition)
        print('\n\n'.join(posts))
        return
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Не задан TELEGRAM_BOT_TOKEN.')
    for index, post in enumerate(posts, 1):
        response = request_json(f'https://api.telegram.org/bot{token}/sendMessage',
                                {'chat_id': os.environ.get('TELEGRAM_CHANNEL', '@proastrologi'),
                                 'text': post, 'parse_mode': 'HTML'})
        if not response.get('ok'):
            raise RuntimeError(f'Telegram отклонил сообщение {index}; остановка без повторной отправки.')
        print(f'Отправлено {index}/12; message_id={response["result"]["message_id"]}', flush=True)
        time.sleep(1)
    remember(day, edition)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        sys.exit(1)
