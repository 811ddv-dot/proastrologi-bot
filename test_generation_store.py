import base64
import copy
import json
import os
import unittest
from datetime import date
from unittest.mock import patch

import daily_horoscope as bot
from generation_store import GenerationStore, fingerprint


class FakeRepository:
    def __init__(self):
        self.files = {}
        self.writes = 0

    def __call__(self, method, payload=None, path=None):
        if method == 'GET':
            return copy.deepcopy(self.files.get(path))
        old = self.files.get(path)
        if old and old['sha'] != payload.get('sha'):
            raise RuntimeError('Conflict')
        self.writes += 1
        self.files[path] = {'sha': str(self.writes), 'content': payload['content']}
        return {'content': {'sha': str(self.writes)}}


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.day = date(2026, 9, 24)
        self.store = GenerationStore(self.day, self.repo)
        self.budget = bot.RequestBudget()
        self.response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"answer": "saved"}'}}],
                         'usage': {'prompt_tokens': 100, 'completion_tokens': 100}}
        for target, value in [('GENERATION_STORE', self.store), ('API_BUDGET', self.budget)]:
            p = patch.object(bot, target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_completed_response_reused_after_process_restart(self):
        with patch.object(bot, 'request_json', return_value=self.response) as network:
            expected = bot.model_json('SECRET', 'gpt-5.4', 'write', {'date': str(self.day)})
            bot.GENERATION_STORE = GenerationStore(self.day, self.repo)
            self.assertEqual(bot.model_json('SECRET', 'gpt-5.4', 'write', {'date': str(self.day)}), expected)
            self.assertEqual(network.call_count, 1)
        decoded = base64.b64decode(self.repo.files[self.store.path]['content']).decode()
        self.assertNotIn('SECRET', decoded)
        self.assertEqual(self.budget.calls, 1)

    def test_timeout_persists_reservation_and_blocks_paid_retry(self):
        with patch.object(bot, 'request_json', side_effect=TimeoutError) as network:
            with self.assertRaises(TimeoutError):
                bot.model_json('test', 'gpt-5.4', 'write', {})
            bot.GENERATION_STORE = GenerationStore(self.day, self.repo)
            with self.assertRaisesRegex(RuntimeError, 'неизвестный'):
                bot.model_json('test', 'gpt-5.4', 'write', {})
            self.assertEqual(network.call_count, 1)
        self.assertGreater(bot.GENERATION_STORE.data['spent'], 0)

    def test_checkpoint_failure_prevents_paid_request(self):
        with patch.object(self.store, 'save', side_effect=RuntimeError('storage')), \
                patch.object(bot, 'request_json') as network:
            with self.assertRaises(RuntimeError):
                bot.model_json('test', 'gpt-5.4', 'write', {})
            network.assert_not_called()

    def test_changed_inputs_cannot_use_old_answer(self):
        with patch.object(bot, 'request_json', return_value=self.response) as network:
            bot.model_json('test', 'gpt-5.4', 'write', {'history': []})
            bot.model_json('test', 'gpt-5.4', 'write', {'history': ['new']})
            self.assertEqual(network.call_count, 2)

    def test_concurrent_revision_blocks_second_writer(self):
        other = GenerationStore(self.day, self.repo)
        self.store.begin('one', self.budget)
        with self.assertRaisesRegex(RuntimeError, 'Conflict'):
            other.begin('two', self.budget)

    def test_delivery_ambiguous_result_never_retried(self):
        bundle = {'date': str(self.day), 'forecasts': {s: 'Текст.' for s in bot.SIGNS}}
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test'}), \
                patch.object(bot, 'request_json', side_effect=TimeoutError) as network:
            with self.assertRaises(TimeoutError):
                bot.publish_bundle(self.day, bundle)
            bot.GENERATION_STORE = GenerationStore(self.day, self.repo)
            with self.assertRaisesRegex(RuntimeError, 'повторная'):
                bot.publish_bundle(self.day, bundle)
            self.assertEqual(network.call_count, 1)

    def test_sent_delivery_recovers_history_without_resending(self):
        bundle = {'date': str(self.day), 'forecasts': {s: 'Текст.' for s in bot.SIGNS}}
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test'}), \
                patch.object(bot, 'request_json', return_value={'ok': True, 'result': {'message_id': 78}}) as network, \
                patch.object(bot, 'remember', side_effect=[RuntimeError('disk'), None]) as remember:
            with self.assertRaises(RuntimeError):
                bot.publish_bundle(self.day, bundle)
            bot.GENERATION_STORE = GenerationStore(self.day, self.repo)
            bot.publish_bundle(self.day, bundle)
            self.assertEqual(network.call_count, 1)
            self.assertEqual(remember.call_count, 2)

    def test_budget_restored_across_runs(self):
        self.budget.calls, self.budget.spent = 8, .4
        self.store.begin('pending', self.budget)
        with patch.dict(os.environ, {'DURABLE_GENERATION': 'true'}), \
                patch('history_store.api', self.repo), patch.object(bot, 'API_BUDGET', bot.RequestBudget()):
            bot.open_generation_store(self.day)
            self.assertEqual(bot.API_BUDGET.calls, 8)
            self.assertEqual(bot.API_BUDGET.spent, .4)

    def test_canonical_fingerprint(self):
        self.assertEqual(fingerprint({'a': 1, 'b': 2}), fingerprint({'b': 2, 'a': 1}))

    def test_main_blocks_generation_after_ambiguous_delivery(self):
        self.store.data['delivery'] = {'status': 'pending'}
        with patch('sys.argv', ['daily_horoscope.py', '--tomorrow']), \
                patch.object(bot, 'next_edition_date', return_value=self.day), \
                patch.object(bot, 'read_history', return_value=[]), \
                patch.object(bot, 'open_generation_store'), \
                patch.object(bot, 'generate_bundle') as generate:
            with self.assertRaisesRegex(RuntimeError, 'неизвестен'):
                bot.main()
            generate.assert_not_called()

    def test_main_recovers_sent_bundle_without_model(self):
        bundle = {'date': str(self.day), 'forecasts': {s: 'Текст.' for s in bot.SIGNS}}
        self.store.data['delivery'] = {'status': 'sent', 'bundle': bundle}
        with patch('sys.argv', ['daily_horoscope.py', '--tomorrow']), \
                patch.object(bot, 'next_edition_date', return_value=self.day), \
                patch.object(bot, 'read_history', return_value=[]), \
                patch.object(bot, 'open_generation_store'), \
                patch.object(bot, 'generate_bundle') as generate, \
                patch.object(bot, 'publish_bundle') as send, \
                patch.object(bot, 'remember') as remember:
            bot.main()
            generate.assert_not_called()
            send.assert_not_called()
            remember.assert_called_once_with(bundle)

    def test_corrupt_checkpoint_blocks_loading(self):
        self.store.save()
        self.repo.files[self.store.path]['content'] = base64.b64encode(b'{"version":99}').decode()
        with self.assertRaises(ValueError):
            GenerationStore(self.day, self.repo)


if __name__ == '__main__':
    unittest.main()
