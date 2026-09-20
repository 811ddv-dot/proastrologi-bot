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
APPROVED_DATE = '2026-09-19'
APPROVED = {
    'Овен': 'Дело, которое долго стояло на месте, может наконец сдвинуться благодаря вашей инициативе. Вместо долгих объяснений предложите конкретный шаг — окружающим будет проще вас поддержать. Однако чужая медлительность ещё не повод брать всё на себя: дайте людям возможность включиться в своём темпе. Сегодня ваша решительность особенно полезна там, где уже понятно, чего вы хотите добиться.',
    'Телец': 'Захочется сделать повседневную жизнь удобнее: разобраться с накопившимися мелочами, освободить пространство или вернуться к привычному занятию. Не обязательно затевать большие перемены — небольшое улучшение принесёт больше удовольствия, чем грандиозный план. Покупку, которая привлекла красивой картинкой, стоит оценить с практической стороны. Умение отличать действительно нужное от мимолётного желания сегодня вас выручит.',
    'Близнецы': 'Случайная переписка может возобновить общение, которого вам не хватало. Не старайтесь сразу заполнить все паузы: интересный поворот появится, если внимательнее слушать собеседника. Среди новостей найдётся тема, которую захочется изучить глубже, но первые впечатления могут оказаться неполными. Ваше любопытство поможет задать именно тот вопрос, после которого многое станет понятнее.',
    'Рак': 'Привычная просьба близкого человека может вызвать неожиданное раздражение. Возможно, дело в накопившейся усталости и желании наконец оставить время для себя. Скажите об этом прямо и спокойно, не рассчитывая, что ваше настроение угадают. Чуткость поможет найти тёплые слова, а честность избавит от необходимости соглашаться на то, к чему сейчас не лежит душа.',
    'Лев': 'Вас могут пригласить туда, где получится проявить себя с непривычной стороны. Не стоит заранее придумывать эффектную роль: живой интерес и чувство юмора произведут лучшее впечатление. Если окажетесь в центре внимания, вовлеките в разговор того, кто держится в стороне. Ваша способность придать людям уверенности сделает встречу приятной и поможет завязать новое знакомство.',
    'Дева': 'Незавершённая мелочь будет отвлекать сильнее, чем крупные задачи. Разберитесь с ней, пока она снова не затерялась в списке дел: после этого станет легче сосредоточиться. При пересмотре старого плана вы можете обнаружить лишний шаг и заметно упростить себе работу. Внимание к деталям принесёт пользу, если вовремя остановиться и признать хороший результат достаточным.',
    'Весы': 'Два одинаково привлекательных предложения могут поставить вас перед выбором. Вместо попытки угодить всем подумайте, какое из них отвечает вашим собственным желаниям. Объяснять своё решение до тех пор, пока с ним согласятся абсолютно все, не потребуется. Присущее вам чувство такта позволит отказаться от одного варианта и сохранить добрые отношения.',
    'Скорпион': 'Человек, чьи поступки казались странными, может раскрыть важную для понимания ситуации подробность. Не спешите превращать разговор в проверку: доверительный тон даст больше, чем настойчивые расспросы. Вы умеете замечать противоречия, но сегодня полезно оставить место и для простого объяснения. Новая информация поможет пересмотреть прежний вывод и снять ненужное напряжение.',
    'Стрелец': 'Привычный маршрут покажется тесным, и желание сменить обстановку окажется вполне осуществимым. Небольшая поездка, незнакомое место или занятие вне обычного расписания подарят свежие впечатления. Оставьте в плане свободное время, чтобы не превратить отдых в гонку по обязательным пунктам. Ваша открытость новому поможет получить удовольствие даже от неожиданного изменения маршрута.',
    'Козерог': 'Вас могут снова попросить выручить там, где привыкли полагаться на вашу ответственность. Прежде чем согласиться, оцените, сколько времени это действительно займёт и что придётся отложить. Чёткая договорённость об объёме помощи убережёт от лишней нагрузки. Умение доводить начатое до конца сегодня лучше направить на одно собственное дело, результат которого давно хочется увидеть.',
    'Водолей': 'Идея, которая кажется вам очевидной, поначалу может встретить недоумение. Покажите её на простом примере — так будет легче найти человека, готового попробовать вместе с вами. Неожиданное замечание со стороны поможет доработать замысел, поэтому не отмахивайтесь от вопросов. Ваша изобретательность особенно пригодится для решения небольшой, но давно надоевшей проблемы.',
    'Рыбы': 'Книга, музыка или давно забытая фотография могут вернуть вас к занятию, которое когда-то радовало. Позвольте себе увлечься им без требования сразу получить полезный результат. Если захочется поделиться воспоминанием, выберите человека, с которым можно говорить без спешки. Богатое воображение поможет по-новому взглянуть на знакомую историю и найти в ней вдохновение.',
}
PROMPT = '''Ты редактор оригинального развлекательного ежедневного гороскопа на русском языке.
Напиши весь выпуск сразу: для каждого из 12 знаков отдельный общий прогноз.
Стиль — спокойный, содержательный, редакционный: не мини-история и не набор ярких событий. Сначала кратко оцени общий характер дня для этого знака, затем назови вероятную трудность или удачную возможность, после чего дай точный практический совет. Пиши естественно и уверенно, без пафоса.
Один связный абзац на 65-105 слов; 4-6 предложений. Обращение на «вы».
Не привязывай каждый текст к одному событию вроде звонка, покупки или встречи. Лучше говори о делах, договорённостях, общении, деньгах, планах и личных отношениях так, как это обычно происходит в течение дня. Допускаются конкретные детали, но только если они помогают прогнозу, а не заменяют его сюжетом.
У каждого знака должны различаться настроение дня, степень осторожности, сфера внимания и совет. Не используй один и тот же ход: «событие — сомнение — совет — оптимистичный финал». Не закрепляй одну тему за знаком навсегда.
Встраивай характер знака естественно. Не используй формулы «ваша сила», «ваше умение», «в итоге» и «в результате». Избегай канцелярита: «ресурс», «перспектива», «ясность», «значимые дела».
Без рубрик по времени суток, списков, хэштегов, заголовков и эмодзи внутри текста.
Без копирования Mail.ru и других изданий: ориентируйся только на общую манеру — сдержанный прогноз, реальные жизненные сферы и полезный совет. Не используй чужие фразы и не пересказывай чужие тексты. Без заявлений о рассчитанных транзитах планет, гарантированных событий, диагнозов, обещаний дохода или запугивания.
Примеры ниже задают только качество и стиль. Не копируй их и не пересказывай их сюжеты.
Верни JSON-объект: ключ — русское название знака, значение — только текст абзаца.
'''

# No fixed sign examples: they anchor the model to yesterday's themes.
PROMPT = '''Напиши оригинальный развлекательный гороскоп на русском для всех 12 знаков.
Для каждого знака один связный абзац, 65–105 слов, 4–6 естественных предложений, обращение на «вы».
Нужен живой редакционный общий прогноз: сочетай две или три жизненные сферы,
связывая их по смыслу, а не перечисляя. Пусть читатель узнаёт ситуации своей жизни.
Пиши о возможностях и вероятных событиях, а не только о характере человека и советах.
Балансируй благоприятные, спокойные и неоднозначные дни между знаками.
Не назначай всем проблему и обязательный совет. Меняй порядок мыслей, длину предложений,
настроение, начало и концовку. Не строй 12 текстов по одинаковой композиции.
Без явных меток «риск», «трудность», «опасность», «совет дня» и канцелярских оборотов.
Не закрепляй за Тельцом покупки, Девой порядок, Рыбами творчество и прочие стереотипы.
Не повторяй темы, основные события и советы из приложенной истории, особенно для того же знака.
Различие слов при сохранении прежнего смысла не считается новым прогнозом.
Простой грамотный русский язык, плавные переходы, никаких натянутых метафор или нравоучений.
Без утра, вечера, рубрик, списков, эмодзи, хэштегов и разметки внутри абзацев.
Не копируй и не пересказывай Mail.ru или другие издания. Не заявляй о расчёте планет.
Без гарантированных событий, медицинских и инвестиционных рекомендаций или запугивания.
Верни JSON: русское название каждого знака — текст его прогноза.
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
        if re.search(r'\b(утро\w*|вечер\w*)\b', body.lower()):
            raise ValueError(f'{sign}: убрать деление по времени суток.')
    for a, b in combinations(edition, 2):
        if grams(edition[a]) & grams(edition[b]):
            raise ValueError(f'Повторяющаяся формулировка: {a}, {b}.')
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
    for attempt in range(3):
        try:
            edition = validate(model_json(key, model, PROMPT, {
                'date': day.isoformat(), 'signs': list(SIGNS), 'history': history,
                'editor_feedback': feedback}))
            validate_originality(edition, history)
            review = model_json(key, model,
                'Ты строгий литературный редактор. Проверь выпуск по заданию. '
                'Особенно проверь одинаковую композицию у знаков, повтор сюжетов и советов '
                'из истории, стереотипы знаков, неестественный русский язык и избыток наставлений. '
                'Не принимай набор психологических советов за прогноз. '
                'Верни JSON {"approved": true/false, "issues": [конкретные замечания с названием знака]}. '
                'Одобряй только если существенных недостатков нет.',
                {'requirements': PROMPT, 'edition': edition, 'history': history})
            if review.get('approved') is not True or review.get('issues') != []:
                raise ValueError('Редактор: ' + json.dumps(review.get('issues', ['Нет одобрения']), ensure_ascii=False))
            return edition
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            feedback.append(str(exc))
    raise RuntimeError('Выпуск не прошёл проверку после трёх попыток. Ничего не опубликовано.')


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
