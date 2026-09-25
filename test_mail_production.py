import unittest
from datetime import datetime
from unittest.mock import patch, Mock
import mail_production as prod


class MailProductionTests(unittest.TestCase):
    def test_early_call_cannot_publish_or_generate(self):
        with patch.object(prod.mail_preview, 'run') as generate:
            with self.assertRaises(RuntimeError):
                prod.run(now=datetime(2026, 9, 25, 20, 59))
            generate.assert_not_called()

    def test_already_published_skips_everything(self):
        with patch.object(prod.bot, 'read_history', return_value=[{'date': '2026-09-26'}]), \
                patch.object(prod.mail_preview, 'run') as generate:
            prod.run(now=datetime(2026, 9, 25, 21))
            generate.assert_not_called()

    def test_ambiguous_delivery_blocks_generation(self):
        with patch.object(prod.bot, 'read_history', return_value=[]), \
                patch.object(prod, 'GenerationStore', return_value=Mock(data={'delivery': {'status': 'pending'}})), \
                patch.object(prod.mail_preview, 'run') as generate:
            with self.assertRaises(RuntimeError):
                prod.run(now=datetime(2026, 9, 25, 21))
            generate.assert_not_called()

    def test_production_uses_tomorrow_and_shared_delivery_guard(self):
        delivery = Mock(data={})
        summary = Mock(data={'language_editor_version': prod.mail_preview.EDITOR_VERSION,
                            'result': {'forecasts': dict.fromkeys(prod.bot.SIGNS, 'Текст.')},
                            'spent': .03})
        def generate(day):
            self.assertEqual(str(day), '2026-09-26')
            prod.bot.GENERATION_STORE = summary
        with patch.object(prod.bot, 'read_history', return_value=[]), \
                patch.object(prod, 'GenerationStore', return_value=delivery), \
                patch.object(prod.mail_preview, 'run', side_effect=generate), \
                patch.object(prod.bot, 'GENERATION_STORE', None), \
                patch.object(prod.bot, 'publish_bundle') as publish:
            prod.run(now=datetime(2026, 9, 25, 21))
            self.assertIs(prod.bot.GENERATION_STORE, delivery)
            self.assertEqual(publish.call_args.args[1]['date'], '2026-09-26')
