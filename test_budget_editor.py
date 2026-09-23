import unittest
from unittest.mock import patch
from datetime import date
import daily_horoscope as bot
from budget_editor import edit_with_budget, report_text


class BudgetEditorTests(unittest.TestCase):
    def run_editor(self, responses, issues=None, review=None):
        edition = {s: 'Текст ' + s for s in bot.SIGNS}
        with patch.object(bot, 'GENERATION_STORE', None), \
             patch.object(bot, 'API_BUDGET', bot.RequestBudget()), \
             patch.object(bot, 'model_json', side_effect=responses), \
             patch.object(bot, 'edition_issues', return_value=issues or {}), \
             patch.object(bot, 'review_edition', side_effect=review or [{}]):
            return edit_with_budget(bot, date(2026, 9, 25), 'test', 'gpt-5.4', {}, edition, {}, [])

    def test_no_complete_post_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'полного пригодного'):
            self.run_editor([bot.BudgetExhausted()])

    def test_budget_during_review_reports_unknown(self):
        edition = {s: 'Текст ' + s for s in bot.SIGNS}
        result = self.run_editor([edition], review=[bot.BudgetExhausted()])
        self.assertEqual(result['forecasts'], edition)
        self.assertIsNone(result['editorial_report']['remaining_signs'])
        self.assertIn('неизвестно', report_text(result['editorial_report']))

    def test_incomplete_repair_uses_previous_complete_post(self):
        edition = {s: 'Текст ' + s for s in bot.SIGNS}
        result = self.run_editor([edition, {'Овен': ''}, bot.BudgetExhausted()], {'Овен': ['повтор']})
        self.assertEqual(result['forecasts'], edition)
        self.assertEqual(result['editorial_report']['remaining_signs'], 1)

    def test_review_pass_stops_without_spending_rest(self):
        edition = {s: 'Текст ' + s for s in bot.SIGNS}
        result = self.run_editor([edition])
        self.assertEqual(result['editorial_report']['reason'], 'passed')
        self.assertEqual(result['editorial_report']['repair_rounds'], 0)
        self.assertIn('не требуется', report_text(result['editorial_report']))
