"""Private operational notices; no credentials or forecasts in messages/logs."""
import os
import re
import sys

from daily_horoscope import request_json


def notify(test=False):
    chat_id = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '').strip()
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not chat_id:
        print('::warning::Личные уведомления не подключены: добавьте TELEGRAM_ADMIN_CHAT_ID.')
        return False
    if not re.fullmatch(r'[1-9][0-9]*', chat_id) or not token:
        raise RuntimeError('Нужен ID личного чата и токен бота; отправка в канал запрещена.')
    base = f'https://api.telegram.org/bot{token}/'
    chat = request_json(base + 'getChat', {'chat_id': chat_id})
    if not chat.get('ok') or chat.get('result', {}).get('type') != 'private':
        raise RuntimeError('Получатель уведомлений не подтверждён как личный чат.')
    text = ('Проверка связи: личные уведомления о сбоях @proastrologi подключены. '
            'Это тест, ошибки публикации сейчас нет.' if test else
            '⚠️ В работе @proastrologi произошёл сбой. Проверь запуск по ссылке ниже. '
            'Не перезапускай отправку вслепую: пост мог уйти до ошибки сохранения истории.')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if run_id.isdigit():
        text += f'\nhttps://github.com/811ddv-dot/proastrologi-bot/actions/runs/{run_id}'
    result = request_json(base + 'sendMessage', {'chat_id': chat_id, 'text': text})
    if not result.get('ok'):
        raise RuntimeError('Telegram не принял личное уведомление.')
    print('Личное уведомление доставлено.')
    return True


if __name__ == '__main__':
    try:
        notify(test='--test' in sys.argv)
    except Exception as exc:
        print(f'Ошибка уведомления: {exc}', file=sys.stderr)
        sys.exit(1)
