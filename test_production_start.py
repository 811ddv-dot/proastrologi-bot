import unittest
from datetime import datetime, date
from unittest.mock import patch, Mock
import daily_horoscope as bot

class ProductionStartTests(unittest.TestCase):
    def test_before_start_no_storage_generation_or_publication(self):
        for day in (23, 24):
            with patch.dict('os.environ', {'PRODUCTION_START_DATE': '2026-09-25'}), \
                 patch('sys.argv', ['bot', '--tomorrow']), patch.object(bot, 'datetime') as clock, \
                 patch.object(bot, 'open_generation_store') as store, \
                 patch.object(bot, 'generate_bundle') as generate, patch.object(bot, 'publish_bundle') as publish:
                clock.now.return_value = datetime(2026, 9, day, 21)
                bot.main()
                store.assert_not_called()
                generate.assert_not_called()
                publish.assert_not_called()

    def test_start_day_uses_saved_approved_preview_without_generation(self):
        approved = {'date': '2026-09-26', 'forecasts': {s: 'Готовый текст.' for s in bot.SIGNS}}
        with patch.dict('os.environ', {'PRODUCTION_START_DATE': '2026-09-25'}), \
             patch('sys.argv', ['bot', '--tomorrow']), patch.object(bot, 'datetime') as clock, \
             patch.object(bot, 'next_edition_date', return_value=date(2026, 9, 26)), \
             patch.object(bot, 'read_history', return_value=[]), patch.object(bot, 'open_generation_store'), \
             patch.object(bot, 'GENERATION_STORE', Mock(data={'approved_preview': approved})), \
             patch.object(bot, 'generate_bundle') as generate, patch.object(bot, 'publish_bundle') as publish:
            clock.now.return_value = datetime(2026, 9, 25, 21)
            bot.main()
            generate.assert_not_called()
            self.assertEqual(publish.call_args.args[1]['forecasts'], approved['forecasts'])
