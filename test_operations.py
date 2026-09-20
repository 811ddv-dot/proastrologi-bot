import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_horoscope as bot
import history_store as store
import notify_admin as alerts


def bundle(day):
    return {'date': day, 'forecasts': {sign: 'Опубликованный текст.' for sign in bot.SIGNS}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.state_patch = patch.object(bot, 'STATE', root / 'history.json')
        self.revision_patch = patch.object(store, 'REVISION', root / 'revision.json')
        self.state_patch.start()
        self.revision_patch.start()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.revision_patch.stop)
        self.old = [bundle('2026-09-20')]

    def remote(self, history):
        return {'encoding': 'base64', 'sha': 'old-sha', 'content': store.encoded(history)}

    def test_remote_wins_over_stale_cache(self):
        bot.STATE.write_text(json.dumps([bundle('2026-09-19')]))
        with patch.object(store, 'api', return_value=self.remote(self.old)) as api:
            store.restore()
        api.assert_called_once_with('GET')
        self.assertEqual(bot.read_history(), self.old)

    def test_cache_migrates_once(self):
        bot.STATE.write_text(json.dumps(self.old))
        with patch.object(store, 'api', side_effect=[None, {'content': {'sha': 'new'}}]) as api:
            store.restore()
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[0], 'PUT')
        self.assertEqual(json.loads(base64.b64decode(api.call_args.args[1]['content'])), self.old)

    def test_missing_or_invalid_history_never_replaced_with_empty(self):
        with patch.object(store, 'api', return_value=None) as api:
            with self.assertRaises(ValueError):
                store.restore()
        api.assert_called_once_with('GET')

    def test_network_error_does_not_fallback_to_stale_cache(self):
        bot.STATE.write_text(json.dumps(self.old))
        with patch.object(store, 'api', side_effect=RuntimeError('network')):
            with self.assertRaises(RuntimeError):
                store.restore()
        self.assertFalse(store.REVISION.exists())

    def test_save_uses_revision_and_skips_unchanged(self):
        with patch.object(store, 'api', return_value=self.remote(self.old)):
            store.restore()
        with patch.object(store, 'api') as api:
            store.save()
            api.assert_not_called()
        bot.remember(bundle('2026-09-21'))
        with patch.object(store, 'api', return_value={'content': {'sha': 'next'}}) as api:
            store.save()
        self.assertEqual(api.call_args.args[1]['sha'], 'old-sha')
        self.assertEqual(len(json.loads(base64.b64decode(api.call_args.args[1]['content']))), 2)

    def test_accidental_history_loss_blocks_save(self):
        with patch.object(store, 'api', return_value=self.remote(self.old)):
            store.restore()
        bot.STATE.write_text(json.dumps([bundle('2026-09-21')]))
        with patch.object(store, 'api') as api:
            with self.assertRaises(ValueError):
                store.save()
            api.assert_not_called()

    def test_only_allowed_fields_are_saved(self):
        value = bundle('2026-09-20')
        value['TELEGRAM_BOT_TOKEN'] = 'never-store'
        self.assertNotIn('never-store', json.dumps(store.canonical([value])))


class NotificationTests(unittest.TestCase):
    def test_no_secret_never_sends_to_channel(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(alerts, 'request_json') as request:
            self.assertFalse(alerts.notify())
        request.assert_not_called()

    def test_rejects_channel_destinations(self):
        for chat_id in ('@proastrologi', '-1001234'):
            with patch.dict(os.environ, {'TELEGRAM_ADMIN_CHAT_ID': chat_id, 'TELEGRAM_BOT_TOKEN': 'test'}), \
                    patch.object(alerts, 'request_json') as request:
                with self.assertRaises(RuntimeError):
                    alerts.notify()
            request.assert_not_called()

    def test_private_recipient_and_no_sensitive_error_details(self):
        with patch.dict(os.environ, {'TELEGRAM_ADMIN_CHAT_ID': '1234', 'TELEGRAM_BOT_TOKEN': 'test',
                                     'GITHUB_RUN_ID': '5678'}), \
                patch.object(alerts, 'request_json', side_effect=[
                    {'ok': True, 'result': {'type': 'private'}}, {'ok': True}]) as request:
            self.assertTrue(alerts.notify(test=True))
        payload = request.call_args.args[1]
        self.assertEqual(payload['chat_id'], '1234')
        self.assertIn('Это тест', payload['text'])
        self.assertIn('/runs/5678', payload['text'])


if __name__ == '__main__':
    unittest.main()
