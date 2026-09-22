import unittest
from unittest.mock import patch

import daily_horoscope as bot
from editorial_review import verified_issues


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.edition = {sign: 'Прогноз для знака ' + sign for sign in bot.SIGNS}
        self.issue = {'kind': 'duplicate', 'quote': self.edition['Овен'],
                      'reason': 'Совпали ситуация и развитие.',
                      'reference': {'date': 'current', 'sign': 'Телец',
                                    'quote': self.edition['Телец']}}

    def test_current_duplicate(self):
        result = verified_issues({'issues': {'Овен': self.issue}}, self.edition, [])
        self.assertIn('Овен', result)

    def test_collision_repairs_changed_not_frozen(self):
        result = verified_issues({'issues': {'Овен': self.issue}}, self.edition, [], {'Телец'})
        self.assertEqual(list(result), ['Телец'])
        self.assertEqual(result['Телец'][0]['reference']['sign'], 'Овен')

    def test_false_history_attribution_rejected(self):
        self.issue['reference'] = {'date': '2026-09-21', 'sign': 'Водолей', 'quote': 'Денежный вопрос'}
        history = [{'date': '2026-09-21', 'forecasts': {'Водолей': 'Домашняя тема требует внимания.'}}]
        with self.assertRaises(ValueError):
            verified_issues({'issues': {'Овен': self.issue}}, self.edition, history)

    def test_real_history_reference(self):
        self.issue['reference'] = {'date': '2026-09-21', 'sign': 'Водолей', 'quote': 'Домашняя тема'}
        history = [{'date': '2026-09-21', 'forecasts': {'Водолей': 'Домашняя тема требует внимания.'}}]
        self.assertIn('Овен', verified_issues({'issues': {'Овен': self.issue}}, self.edition, history))
        self.issue['reference']['date'] = '2026-09-20'
        with self.assertRaises(ValueError):
            verified_issues({'issues': {'Овен': self.issue}}, self.edition, history)

    def test_invented_quote_rejected(self):
        self.issue['quote'] = 'Вымышленная цитата'
        with self.assertRaises(ValueError):
            verified_issues({'issues': {'Овен': self.issue}}, self.edition, [])

    def test_frozen_style_rejection(self):
        self.issue['kind'] = 'language'
        with self.assertRaises(ValueError):
            verified_issues({'issues': {'Овен': self.issue}}, self.edition, [], {'Телец'})

    def test_invalid_review_retries_then_fails_closed(self):
        with patch.object(bot, 'model_json', return_value={'issues': {'Овен': 'нет цитаты'}}) as model:
            with self.assertRaises(RuntimeError):
                bot.review_edition('key', 'model', self.edition, [])
            self.assertEqual(model.call_count, 2)

    def test_invalid_review_can_be_corrected(self):
        with patch.object(bot, 'model_json', side_effect=[{'issues': []}, {'issues': {}}]) as model:
            self.assertEqual(bot.review_edition('key', 'model', self.edition, []), {})
            self.assertEqual(model.call_count, 2)

    def test_pending_unchanged_paragraph_stays_in_scope(self):
        self.issue['kind'] = 'language'
        with patch.object(bot, 'model_json', return_value={'issues': {'Овен': self.issue}}) as model:
            result = bot.review_edition('key', 'model', self.edition, [],
                                        dict(self.edition), {'Овен': [self.issue]})
            self.assertIn('Овен', result)
            self.assertEqual(model.call_args.args[3]['review_signs'], ['Овен'])

    def test_initial_review_covers_every_sign(self):
        with patch.object(bot, 'model_json', return_value={'issues': {}}) as model:
            bot.review_edition('key', 'model', self.edition, [])
            self.assertEqual(set(model.call_args.args[3]['review_signs']), set(bot.SIGNS))

    def test_planner_and_reviewer_enable_reasoning(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        for instruction in (bot.PLAN_PROMPT, bot.QUALITY_PROMPT, bot.LANGUAGE_PROMPT, bot.WRITE_PROMPT):
            with patch.object(bot, 'request_json', return_value=response) as request:
                bot.model_json('key', 'gpt-5.4', instruction, {})
                payload = request.call_args.args[1]
                if instruction == bot.WRITE_PROMPT:
                    self.assertNotIn('reasoning_effort', payload)
                else:
                    self.assertEqual(payload['reasoning_effort'], 'low')

    def test_reports_all_bad_evidence_at_once(self):
        issue = {'kind': 'language', 'quote': 'Выдуманная цитата', 'reason': 'Ошибка.'}
        with self.assertRaises(ValueError) as error:
            verified_issues({'issues': {'Овен': issue, 'Телец': issue}}, self.edition, [])
        self.assertIn(self.edition['Овен'], str(error.exception))
        self.assertIn(self.edition['Телец'], str(error.exception))

    def test_review_history_excludes_stale_plans(self):
        history = [{'date': '2026-09-21', 'forecasts': self.edition, 'plan': {'stale': 'plan'}}]
        with patch.object(bot, 'model_json', return_value={'issues': {}}) as model:
            bot.review_edition('key', 'model', self.edition, history)
            self.assertNotIn('plan', model.call_args.args[3]['history'][0])

    def test_format_repairs_do_not_spend_content_budget(self):
        from datetime import date
        from test_daily_horoscope import sample_plan
        edition = dict(self.edition)
        # Five formatting failures plus one semantic failure must still allow success.
        checks = [{'Овен': ['length']}] * 5 + [{}, {}]
        issue = {'Овен': [{'kind': 'language', 'quote': edition['Овен'], 'reason': 'Ошибка'}]}
        with patch.dict(bot.os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'model_json', side_effect=[sample_plan(), edition] + [edition] * 7), \
                patch.object(bot, 'edition_issues', side_effect=checks), \
                patch.object(bot, 'review_edition', side_effect=[issue, {}]):
            self.assertEqual(bot.generate_bundle(date(2026, 9, 22), [])['forecasts'], edition)


if __name__ == '__main__':
    unittest.main()
