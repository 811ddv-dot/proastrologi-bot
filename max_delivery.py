"""MAX delivery of an existing edition; never calls a text generation API."""
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from datetime import date
from generation_store import fingerprint
import daily_horoscope as bot

CHANNEL_ID = -79305594853965
BOT_USERNAME = 'id400406889818_bot'


def enabled():
    return os.environ.get('MAX_ENABLED', '').lower() == 'true'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('MAX redirect refused; credentials not forwarded.')


def request(path, payload=None):
    token = os.environ.get('MAX_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('MAX_BOT_TOKEN отсутствует.')
    # Official public CA, scoped ONLY to this MAX HTTPS client, not the OS.
    # Source: https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer
    context = ssl.create_default_context(cafile=str(Path(__file__).with_name('max-root-ca.pem')))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())
    req = urllib.request.Request('https://platform-api2.max.ru' + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': token, 'Content-Type': 'application/json'})
    try:
        with opener.open(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'MAX HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('MAX: ошибка сети или сертификата.') from None


def publish(bundle, store):
    if not enabled():
        return
    text = bot.format_edition(date.fromisoformat(bundle['date']), bundle['forecasts'], markup=False)
    if len(text.encode('utf-16-le')) // 2 > 4000:
        raise ValueError('MAX: выпуск превышает 4000 символов; текст не обрезан.')
    key = fingerprint({'channel': CHANNEL_ID, 'text': text})
    previous = store.data.get('max_delivery')
    if previous:
        if previous.get('key') == key and previous.get('status') == 'sent':
            print('MAX: выпуск уже отправлен, повтор пропущен.')
            return
        raise RuntimeError('MAX: предыдущая отправка требует проверки; повтор запрещён.')
    me = request('/me')
    if me.get('username') != BOT_USERNAME:
        raise RuntimeError('MAX: токен другого бота; отправка запрещена.')
    member = request(f'/chats/{CHANNEL_ID}/members/me')
    if not member.get('is_admin') or not ({'write', 'post_edit_delete_message'} & set(member.get('permissions') or [])):
        raise RuntimeError('MAX: у бота нет права публикации.')
    store.data['max_delivery'] = {'key': key, 'status': 'pending', 'chat_id': CHANNEL_ID}
    store.save()  # Persist before POST: an uncertain response must never cause duplicates.
    result = request(f'/messages?chat_id={CHANNEL_ID}', {'text': text})
    message = result.get('message', {})
    mid = message.get('body', {}).get('mid')
    if not mid or message.get('recipient', {}).get('chat_id') != CHANNEL_ID:
        raise RuntimeError('MAX: результат отправки не подтверждён; требуется проверка.')
    store.data['max_delivery'].update(status='sent', message_id=mid)
    store.save()
    print('MAX: выпуск опубликован.')
