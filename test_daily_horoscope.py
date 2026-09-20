import os
import unittest
from datetime import date
from unittest.mock import patch

import daily_horoscope as bot


class EditorialTests(unittest.TestCase):
    def test_invalid_review_does_not_approve(self):
        for value in ({}, {'issues': 'none'}, {'issues': [{}]}, {'issues': [{'sign': 'unknown'}]}):
            with self.assertRaises(ValueError):
                bot.review_issues(value)
        self.assertEqual(bot.review_issues({'issues': []}), [])

    def test_only_flagged_sign_rewritten_and_reviewed_again(self):
        edition = {sign: 'original ' + sign for sign in bot.SIGNS}
        issue = {'sign': 'Овен', 'evidence': 'Повтор смысла с Тельцом', 'fix': 'Измени центральную тему'}
        history = [{'date': '2026-09-20', 'forecasts': edition}]
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'read_history', return_value=history), \
                patch.object(bot, 'validate', side_effect=lambda x: x), \
                patch.object(bot, 'validate_originality'), \
                patch.object(bot, 'model_json', side_effect=[edition, {'issues': [issue]},
                                                           {'Овен': 'repaired'}, {'issues': []}]) as model:
            result = bot.generate(date(2026, 9, 21))
        self.assertEqual(result['Овен'], 'repaired')
        self.assertEqual(result['Телец'], edition['Телец'])
        self.assertEqual(model.call_args_list[2].args[3]['repair_signs'], ['Овен'])
        self.assertEqual(model.call_args_list[3].args[3]['history'], history)
        self.assertEqual(model.call_args_list[3].args[3]['edition'], result)

    def test_repeated_semantic_rejection_never_returns_edition(self):
        edition = {sign: 'original ' + sign for sign in bot.SIGNS}
        issue = {'sign': 'Овен', 'evidence': 'Повтор', 'fix': 'Перепиши'}
        responses = [edition, {'issues': [issue]}, {'Овен': 'v2'}, {'issues': [issue]},
                     {'Овен': 'v3'}, {'issues': [issue]}]
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'read_history', return_value=[]), \
                patch.object(bot, 'validate', side_effect=lambda x: x), \
                patch.object(bot, 'validate_originality'), \
                patch.object(bot, 'model_json', side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, 'Ничего не опубликовано'):
                bot.generate(date(2026, 9, 21))

    def test_verbatim_history_rejected(self):
        edition = {sign: ('договорённости изменились и стоит обсудить условия снова ' + sign)
                   for sign in bot.SIGNS}
        with self.assertRaises(ValueError):
            bot.validate_originality(edition, [{'date': '2026-09-20', 'forecasts': edition}])


if __name__ == '__main__':
    unittest.main()
