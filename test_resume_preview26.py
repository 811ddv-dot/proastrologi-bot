import copy
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
import daily_horoscope as bot
import resume_preview26 as resume


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.original = {sign: 'Исходный ' + sign for sign in bot.SIGNS}
        self.store = SimpleNamespace(data={'pending': None, 'repeat_history': [],
            'responses': {resume.BASE_KEYS[0]: self.original, resume.BASE_KEYS[1]: {},
                          resume.BASE_KEYS[2]: {}, resume.REVIEW_KEY: {'issues': {}}}}, save=Mock())
        self.budget = bot.RequestBudget()
        self.budget.spent, self.budget.calls = .51015, 10
        for name, value in [('GENERATION_STORE', self.store), ('API_BUDGET', self.budget)]:
            self.stack.enter_context(patch.object(bot, name, value))
        self.stack.enter_context(patch.object(bot, 'open_generation_store'))
        clock = self.stack.enter_context(patch.object(resume, 'datetime'))
        clock.now.return_value = datetime(2026, 9, 23, tzinfo=ZoneInfo('Europe/Moscow'))
        self.stack.enter_context(patch.dict('os.environ', {'OPENAI_API_KEY': 'offline'}))
        self.stack.enter_context(patch.object(resume, 'full_source_review', return_value={}))
        self.stack.enter_context(patch.object(resume, 'verified_issues', return_value={
            s: [{'kind': 'duplicate', 'reason': 'old plot'}] for s in resume.TARGETS}))
        self.stack.enter_context(patch.object(bot, 'edition_issues', return_value={}))
        self.stack.enter_context(patch.object(bot, 'format_edition', return_value='preview'))
        self.output = self.stack.enter_context(patch.object(resume, 'write_preview'))

    def test_success_only_changes_four_and_keeps_total_cost(self):
        change = {s: 'Новый ' + s for s in resume.TARGETS}
        with patch.object(bot, 'model_json', return_value=change) as model, \
             patch.object(bot, 'review_edition', return_value={}):
            resume.run()
        result = self.store.data['approved_preview']
        for s in set(bot.SIGNS) - resume.TARGETS:
            self.assertEqual(result['forecasts'][s], self.original[s])
        self.assertNotIn('plan', result)
        self.assertEqual(self.budget.spent, .51015)
        self.assertEqual(self.budget.calls, 10)
        self.assertEqual(self.budget.limit, 1)
        payload = model.call_args.args[3]
        self.assertEqual(payload['plan'], {})
        self.assertEqual(set(payload['replace_story']), resume.TARGETS)

    def test_extra_sign_is_rejected(self):
        with patch.object(bot, 'model_json', return_value=self.original), \
             self.assertRaisesRegex(ValueError, 'только проблемные'):
            resume.run()
        self.output.assert_not_called()

    def test_finished_preview_reused_without_paid_request(self):
        self.store.data['approved_preview'] = {'date': str(resume.DAY), 'forecasts': self.original}
        with patch.object(bot, 'model_json') as model:
            resume.run()
        model.assert_not_called()
        self.output.assert_called_once()

    def test_failed_terminal_run_cannot_spend_again(self):
        self.store.data['repair26_finished'] = True
        with patch.object(bot, 'model_json') as model, self.assertRaises(RuntimeError):
            resume.run()
        model.assert_not_called()

    def test_ambiguous_pending_blocks_continuation(self):
        self.store.data['pending'] = 'unknown'
        with patch.object(bot, 'model_json') as model, self.assertRaises(RuntimeError):
            resume.run()
        model.assert_not_called()
