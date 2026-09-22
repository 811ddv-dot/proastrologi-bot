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


if __name__ == '__main__':
    unittest.main()
