import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from stable_astro_editor import edit, confirm_review, recover_legacy_draft
from generation_store import fingerprint


def draft(a='first', b='second'):
    return {'forecasts': {'a': a, 'b': b}, 'basis': {'a': {}, 'b': {}}}


def review(issues=None):
    return {'checks': {}, 'issues': issues or {}}


class StableEditorTests(unittest.TestCase):
    def test_confirmation_explicitly_requests_json_mode(self):
        from stable_astro_editor import CONFIRM_PROMPT
        self.assertIn('JSON', CONFIRM_PROMPT)

    def setup_loop(self, reviews, model_results):
        self.store = SimpleNamespace(data={'result': draft(), 'responses': {}, 'spent': 1.7129375}, save=Mock())
        self.bot = SimpleNamespace(SIGNS=['a', 'b'], ADJUDICATE_PROMPT='original',
            model_json=Mock(side_effect=model_results), format_edition=Mock())
        self.api = SimpleNamespace(EDITOR_VERSION=4, PROMPT='write', validate_basis=Mock(),
            preview_issues=Mock(return_value={}), review_with_retry=Mock(side_effect=reviews))

    def note(self):
        return {'criterion': 'native', 'quote': 'first', 'reason': 'Bad phrasing'}

    def verdict(self, yes=True):
        return {'decisions': [{'id': 'a:0', 'confirmed': yes, 'reason': 'Independent reason'}]}

    def run_loop(self):
        return edit('test', 'date', {}, [], self.store, self.bot, self.api)

    def test_approved_text_not_changed_or_rejudged(self):
        self.setup_loop([review({'a': [self.note()]}), review()],
                        [self.verdict(), draft('fixed', 'unauthorized change')])
        output = self.run_loop()
        self.assertEqual(output, draft('fixed', 'second'))
        self.assertEqual(self.api.review_with_retry.call_args_list[0].args[3], ['a', 'b'])
        self.assertEqual(self.api.review_with_retry.call_args_list[1].args[3], ['a'])
        # All signs remain visible as comparison context for new collisions.
        self.assertEqual(set(self.api.review_with_retry.call_args_list[1].args[1]), {'a', 'b'})
        state = self.store.data['stable_editor']
        self.assertEqual(set(state['accepted']), {'a', 'b'})
        self.assertTrue(state['reviews'])
        self.assertEqual(self.store.data['spent'], 1.7129375)
        calls = self.bot.model_json.call_count
        self.assertEqual(self.run_loop(), output)
        self.assertEqual(self.bot.model_json.call_count, calls)

    def test_disputed_note_does_not_trigger_rewrite(self):
        self.setup_loop([review({'a': [self.note()]})], [self.verdict(False)])
        self.assertEqual(self.run_loop(), draft())
        self.assertEqual(self.bot.model_json.call_count, 1)
        record = next(iter(self.store.data['stable_editor']['reviews'].values()))
        self.assertFalse(record['decisions'][0]['confirmed'])

    def test_missing_confirmation_fails_closed(self):
        self.setup_loop([review({'a': [self.note()]})], [{'decisions': []}])
        with self.assertRaises(ValueError):
            self.run_loop()
        self.assertEqual(self.store.data['stable_editor']['accepted'], {})

    def test_resume_after_repair_keeps_latest_draft(self):
        self.setup_loop([review({'a': [self.note()]}), RuntimeError('budget')],
                        [self.verdict(), draft('fixed')])
        with self.assertRaises(RuntimeError):
            self.run_loop()
        self.assertEqual(self.store.data['stable_editor']['draft'], draft('fixed'))
        self.api.review_with_retry = Mock(return_value=review())
        self.bot.model_json = Mock(side_effect=AssertionError('No paid rewrite expected'))
        self.assertEqual(self.run_loop(), draft('fixed'))
        self.assertEqual(self.api.review_with_retry.call_args.args[3], ['a'])

    def test_same_text_repair_stops_loop(self):
        self.setup_loop([review({'a': [self.note()]})], [self.verdict(), draft()])
        with self.assertRaisesRegex(RuntimeError, 'не изменила'):
            self.run_loop()

    def test_history_change_invalidates_acceptance(self):
        self.setup_loop([review(), review()], [])
        self.run_loop()
        edit('test', 'date', {}, [{'date': 'new'}], self.store, self.bot, self.api)
        self.assertEqual(self.api.review_with_retry.call_args.args[3], ['a', 'b'])

    def test_persistent_round_cap(self):
        self.setup_loop([review({'a': [self.note()]})], [self.verdict(), draft('fixed')])
        with self.assertRaisesRegex(RuntimeError, 'stop'):
            self.api.review_with_retry.side_effect = [review({'a': [self.note()]}), RuntimeError('stop')]
            self.run_loop()
        state = self.store.data['stable_editor']
        state['rounds'] = 8
        self.api.review_with_retry = Mock(return_value=review({'a': [dict(self.note(), quote='fixed')]}))
        self.bot.model_json = Mock(return_value=self.verdict())
        with self.assertRaisesRegex(RuntimeError, 'Восемь'):
            self.run_loop()
        self.assertEqual(self.bot.model_json.call_count, 1)  # confirmation only, no rewrite

    def test_legacy_replay_preserves_unchanged_text(self):
        data = {'result': draft(), 'responses': {
            'repair1': draft('fixed', 'must not change'),
            'review1': {'checks': {}, 'issues': {'b': [{'reason': 'fix b'}]}},
            'repair2': draft('must not change either', 'fixed b'),
            'review2': {'checks': {}, 'issues': {}}}}
        def local(text, history):
            return {'a': ['fix']} if text['a'] == 'first' else {}
        original = deepcopy(data)
        self.assertEqual(recover_legacy_draft(data, local), draft('fixed', 'fixed b'))
        self.assertEqual(data, original)


if __name__ == '__main__':
    unittest.main()
