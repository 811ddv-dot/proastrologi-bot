import unittest
from datetime import date, datetime
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo
import daily_horoscope as bot
import publication_test as test
from test_generation_store import FakeRepository


class FullCycleTests(unittest.TestCase):
    def test_total_cost_restored_and_old_journal_untouched(self):
        repo = FakeRepository()
        with patch('history_store.api', repo), patch.object(bot, 'API_BUDGET'), patch.object(bot, 'GENERATION_STORE'):
            test.open_full25_store(date(2026, 9, 25))
            bot.API_BUDGET.calls, bot.API_BUDGET.spent = 5, .65
            bot.GENERATION_STORE.begin('pending', bot.API_BUDGET)
            test.open_full25_store(date(2026, 9, 25))
            self.assertEqual(bot.API_BUDGET.spent, .65)
            self.assertEqual(bot.API_BUDGET.limit, 1)
            self.assertEqual(set(repo.files), {'generation-state/2026-09-25-scheduled-test-2.json'})
            with self.assertRaises(RuntimeError):
                bot.API_BUDGET.reserve('gpt-5.4', [{'content': 'x' * 120000}], 6000)

    def test_failed_test_cannot_generate_again(self):
        store = Mock(data={'test_finished': True})
        with patch.object(test, 'datetime') as clock, patch.object(test, 'open_full25_store'), \
             patch.object(bot, 'GENERATION_STORE', store), \
             patch.object(bot, 'read_history', return_value=[{'date': '2026-09-24'}]), \
             patch.object(bot, 'generate_bundle') as generate, patch.object(bot, 'publish_bundle') as publish:
            clock.now.return_value = datetime(2026, 9, 23, tzinfo=ZoneInfo('Europe/Moscow'))
            with self.assertRaisesRegex(RuntimeError, 'уже завершён'):
                test.run('full25')
            generate.assert_not_called()
            publish.assert_not_called()

    def test_published_day_skipped_before_any_paid_call(self):
        with patch.object(test, 'datetime') as clock, \
             patch.object(bot, 'read_history', return_value=[{'date': '2026-09-25'}]), \
             patch.object(test, 'open_full25_store') as open_store:
            clock.now.return_value = datetime(2026, 9, 23, tzinfo=ZoneInfo('Europe/Moscow'))
            test.run('full25')
            open_store.assert_not_called()
