"""Durable publication history. Only published bundles, never credentials."""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import daily_horoscope as bot

REMOTE_PATH = 'published-history.json'
REPOSITORY = '811ddv-dot/proastrologi-bot'
REVISION = Path('horoscope-state/durable-revision.json')


def canonical(history):
    if not isinstance(history, list) or not history:
        raise ValueError('История пуста или повреждена; автоматическая перезапись запрещена.')
    cleaned = []
    dates = set()
    for item in history:
        day = date.fromisoformat(item['date']).isoformat()
        if day in dates:
            raise ValueError('В истории повторяется дата.')
        dates.add(day)
        bot.format_edition(date.fromisoformat(day), item['forecasts'])
        entry = {'date': day, 'forecasts': item['forecasts']}
        if 'plan' in item:
            bot.validate_plan(item['plan'], [])
            entry['plan'] = {sign: {field: values[field] for field in
                                   ('domain', 'mood', 'situation', 'turn', 'ending')}
                             for sign, values in item['plan'].items()}
        cleaned.append(entry)
    return sorted(cleaned, key=lambda item: item['date'])[-bot.HISTORY_LIMIT:]


def api(method, payload=None, path=REMOTE_PATH):
    token = os.environ.get('GH_HISTORY_TOKEN', '')
    if not token:
        raise RuntimeError('Не задан служебный токен GitHub для истории.')
    url = f'https://api.github.com/repos/{REPOSITORY}/contents/{path}'
    if method == 'GET':
        url += '?ref=main'
    request = urllib.request.Request(
        url, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'proastrologi-history'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if method == 'GET' and exc.code == 404:
            return None
        raise RuntimeError(f'GitHub history: HTTP {exc.code}; проверьте права записи.') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('GitHub history: сеть недоступна; история не сбрасывается.') from None


def encoded(history):
    raw = json.dumps(canonical(history), ensure_ascii=False, indent=2) + '\n'
    return base64.b64encode(raw.encode()).decode()


def remote_history(remote):
    if remote.get('encoding') != 'base64' or not remote.get('sha'):
        raise ValueError('Некорректный ответ хранилища истории.')
    return canonical(json.loads(base64.b64decode(remote['content'])))


def restore():
    remote = api('GET')
    if remote is None:
        # Migration requires a valid existing cache. Never start silently from [].
        history = canonical(bot.read_history())
        result = api('PUT', {'message': 'Preserve existing publication history',
                            'branch': 'main', 'content': encoded(history)})
        sha = result['content']['sha']
        print('История перенесена из кэша в репозиторий.')
    else:
        history = remote_history(remote)
        sha = remote['sha']
    bot.STATE.parent.mkdir(parents=True, exist_ok=True)
    bot.STATE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
    REVISION.write_text(json.dumps({'sha': sha, 'history': history}, ensure_ascii=False), encoding='utf-8')
    print(f'Постоянная история загружена: {len(history)} выпусков.')


def save():
    previous = json.loads(REVISION.read_text(encoding='utf-8'))
    history = canonical(bot.read_history())
    if history == previous['history']:
        print('История не изменилась; новая запись не требуется.')
        return
    # Reject accidental deletion/modification of old entries, allowing only retention expiry.
    additions = [item for item in history if item['date'] > previous['history'][-1]['date']]
    if history != canonical(previous['history'] + additions):
        raise ValueError('Старая публикация изменилась; сохранение остановлено.')
    if history[-1]['date'] <= previous['history'][-1]['date']:
        raise ValueError('Новый выпуск не найден; сохранение остановлено.')
    result = api('PUT', {'message': f'Preserve published horoscope {history[-1]["date"]}',
                        'branch': 'main', 'sha': previous['sha'], 'content': encoded(history)})
    REVISION.write_text(json.dumps({'sha': result['content']['sha'], 'history': history},
                                  ensure_ascii=False), encoding='utf-8')
    print(f'Постоянная история сохранена: {len(history)} выпусков.')


if __name__ == '__main__':
    try:
        {'restore': restore, 'save': save}[sys.argv[1]]()
    except Exception as exc:
        print(f'Ошибка истории: {exc}', file=sys.stderr)
        sys.exit(1)
