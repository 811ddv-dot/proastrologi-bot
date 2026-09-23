import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
import daily_horoscope as bot


class PreviewBudgetTests(unittest.TestCase):
    def setUp(self):
        self.budget = bot.RequestBudget()
        p = patch.object(bot, 'API_BUDGET', self.budget)
        p.start()
        self.addCleanup(p.stop)
        self.now = datetime(2026, 9, 23, 3, tzinfo=ZoneInfo('Europe/Moscow'))

    def test_continuation_counts_previous_cost(self):
        self.budget.spent, self.budget.calls = .197635, 3
        bot.authorize_preview_budget(date(2026, 9, 26), 1, True, self.now)
        self.assertEqual(self.budget.limit, 1)
        self.assertEqual(self.budget.spent, .197635)
        self.assertEqual(self.budget.calls, 3)
        self.budget.reserve('gpt-5.4', [{'content': 'x' * 100000}], 6000)
        self.assertGreater(self.budget.spent, .5)
        self.budget.spent = .99
        with self.assertRaises(RuntimeError):
            self.budget.reserve('gpt-5.4', [{'content': 'x'}], 6000)

    def test_other_runs_keep_default(self):
        for day, count, preview, now in [
            (date(2026, 9, 26), 1, False, self.now),
            (date(2026, 9, 27), 1, True, self.now),
            (date(2026, 9, 26), 3, True, self.now),
            (date(2026, 9, 26), 1, True, self.now.replace(day=24))]:
            bot.authorize_preview_budget(day, count, preview, now)
            self.assertEqual(self.budget.limit, 1)
            self.assertEqual(self.budget.max_calls, 1000)
