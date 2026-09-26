import unittest
from unittest.mock import Mock, patch
import max_delivery as mx
import mail_production as prod
from datetime import datetime


class MaxDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'MAX_ENABLED': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bundle = {'date': '2026-09-27', 'forecasts': dict.fromkeys(mx.bot.SIGNS, 'Хороший день.')}
        self.store = Mock(data={})

    def responses(self):
        return [{'username': mx.BOT_USERNAME}, {'is_admin': True, 'permissions': ['write']},
                {'message': {'body': {'mid': 'abc'}, 'recipient': {'chat_id': mx.CHANNEL_ID}}}]

    def test_success_and_repeat(self):
        with patch.object(mx, 'request', side_effect=self.responses()) as req:
            mx.publish(self.bundle, self.store)
            self.assertEqual(self.store.data['max_delivery']['status'], 'sent')
            self.assertEqual(self.store.save.call_count, 2)
            mx.publish(self.bundle, self.store)
            self.assertEqual(req.call_count, 3)

    def test_network_failure_never_resends(self):
        with patch.object(mx, 'request', side_effect=self.responses()[:2] + [TimeoutError()]):
            with self.assertRaises(TimeoutError):
                mx.publish(self.bundle, self.store)
        with patch.object(mx, 'request') as req:
            with self.assertRaises(RuntimeError):
                mx.publish(self.bundle, self.store)
            req.assert_not_called()

    def test_checkpoint_failure_prevents_send(self):
        self.store.save.side_effect = RuntimeError('GitHub unavailable')
        with patch.object(mx, 'request', side_effect=self.responses()) as req:
            with self.assertRaises(RuntimeError):
                mx.publish(self.bundle, self.store)
            self.assertEqual(req.call_count, 2)

    def test_wrong_bot_or_missing_permission_blocks_post(self):
        for responses in [[{'username': 'wrong'}], [self.responses()[0], {'is_admin': False}]]:
            with self.subTest(responses=responses), patch.object(mx, 'request', side_effect=responses):
                with self.assertRaises(RuntimeError):
                    mx.publish(self.bundle, self.store)
        self.store.save.assert_not_called()

    def test_wrong_recipient_remains_pending(self):
        responses = self.responses()
        responses[-1]['message']['recipient']['chat_id'] = 1
        with patch.object(mx, 'request', side_effect=responses):
            with self.assertRaises(RuntimeError):
                mx.publish(self.bundle, self.store)
        self.assertEqual(self.store.data['max_delivery']['status'], 'pending')

    def test_published_telegram_resumes_only_max(self):
        with patch.object(prod.bot, 'read_history', return_value=[self.bundle]), \
             patch.object(prod, 'GenerationStore', return_value=self.store), \
             patch.object(prod.mail_preview, 'run') as generate, \
             patch.object(prod.bot, 'publish_bundle') as telegram, \
             patch.object(mx, 'publish') as publish:
            prod.run(now=datetime(2026, 9, 26, 21))
            publish.assert_called_once_with(self.bundle, self.store)
            generate.assert_not_called()
            telegram.assert_not_called()

    def test_disabled_no_network(self):
        with patch.dict('os.environ', {'MAX_ENABLED': 'false'}), patch.object(mx, 'request') as req:
            mx.publish(self.bundle, self.store)
            req.assert_not_called()

    def test_long_edition_no_network(self):
        with patch.object(mx.bot, 'format_edition', return_value='а' * 4001), patch.object(mx, 'request') as req:
            with self.assertRaises(ValueError):
                mx.publish(self.bundle, self.store)
            req.assert_not_called()
