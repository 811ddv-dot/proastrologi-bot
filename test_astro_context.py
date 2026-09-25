import unittest
from astro_context import house, aspects, signed_angle, SIGNS
from astro_preview import validate_basis, preview_issues, editorial_issues, EDITOR_CRITERIA, review_with_retry
from unittest.mock import patch

class AstroTests(unittest.TestCase):
    def test_malformed_review_gets_bounded_retry(self):
        with patch('astro_preview.bot.model_json', side_effect=[{'issues': {}}, self.clean_review()]) as model:
            self.assertEqual(review_with_retry('test', {}, []), {})
            self.assertEqual(model.call_count, 2)
        with patch('astro_preview.bot.model_json', return_value={'issues': {}}) as model:
            with self.assertRaises(ValueError):
                review_with_retry('test', {}, [])
            self.assertEqual(model.call_count, 3)

    def clean_review(self):
        return {'checks': {s: {c: True for c in EDITOR_CRITERIA} for s in SIGNS}, 'issues': {}}

    def test_editor_requires_real_quote(self):
        forecasts = {'Овен': 'Домашняя сторона жизни.'}
        review = self.clean_review()
        review['checks']['Овен']['native'] = False
        review['issues']['Овен'] = [{'criterion': 'native', 'quote': 'Домашняя сторона', 'reason': 'Неестественное сочетание.'}]
        self.assertIn('Овен', editorial_issues(review, forecasts))
        review['issues']['Овен'][0]['quote'] = 'Несуществующая цитата'
        with self.assertRaises(ValueError):
            editorial_issues(review, forecasts)
        self.assertEqual(editorial_issues(self.clean_review(), forecasts), {})

    def test_empty_old_review_cannot_pass(self):
        with self.assertRaises(ValueError):
            editorial_issues({'issues': {}}, {})

    def test_checks_must_cover_every_sign_and_criterion(self):
        review = self.clean_review()
        del review['checks']['Овен']['tone']
        with self.assertRaises(ValueError):
            editorial_issues(review, {})
        review = self.clean_review()
        review['checks']['Овен']['tone'] = 'true'
        with self.assertRaises(ValueError):
            editorial_issues(review, {})

    def test_failed_criterion_requires_evidence(self):
        review = self.clean_review()
        review['checks']['Овен']['coherence'] = False
        with self.assertRaises(ValueError):
            editorial_issues(review, {})

    def test_repeat_requires_second_source(self):
        forecasts = {'Овен': 'Нужно обсудить условия.', 'Телец': 'Обсудите условия встречи.'}
        review = self.clean_review()
        review['checks']['Овен']['intra_repeat'] = False
        note = {'criterion': 'intra_repeat', 'quote': 'обсудить условия', 'reason': 'Тот же сюжет.'}
        review['issues']['Овен'] = [note]
        with self.assertRaises(ValueError):
            editorial_issues(review, forecasts)
        note['reference'] = {'sign': 'Телец', 'quote': 'Обсудите условия'}
        self.assertIn('Овен', editorial_issues(review, forecasts))
        note['reference']['sign'] = 'Овен'
        with self.assertRaises(ValueError):
            editorial_issues(review, forecasts)

    def test_history_repeat_requires_published_quote(self):
        review = self.clean_review()
        review['checks']['Овен']['history_repeat'] = False
        review['issues']['Овен'] = [{'criterion': 'history_repeat', 'quote': 'Покупка', 'reason': 'Повтор.',
            'reference': {'date': '2026-09-25', 'sign': 'Телец', 'quote': 'Покупка'}}]
        with self.assertRaises(ValueError):
            editorial_issues(review, {'Овен': 'Покупка'}, [])
        history = [{'date': '2026-09-25', 'forecasts': {'Телец': 'Покупка'}}]
        self.assertIn('Овен', editorial_issues(review, {'Овен': 'Покупка'}, history))

    def test_rejected_phrases_block_without_paid_review(self):
        with patch('astro_preview.bot.edition_issues', side_effect=lambda *args: {}):
            for phrase in ('Поддержит лёгкую встречу.', 'В центре маленькой симпатии.',
                           'Переделывать договорённость.', 'День любит вашу инициативу.',
                           'Отказываться из лени не стоит.'):
                self.assertIn('Овен', preview_issues({'Овен': phrase}, []))

    def test_foreign_word_is_rejected(self):
        with patch('astro_preview.bot.edition_issues', side_effect=lambda *args: {}):
            self.assertIn('Скорпион', preview_issues({'Скорпион': 'Может quietly напомнить.'}, []))
            self.assertEqual(preview_issues({'Скорпион': 'Может тихо напомнить.'}, []), {})

    def test_wraparound(self):
        self.assertEqual(signed_angle(1-359), 2)
        self.assertEqual(signed_angle(359-1), -2)
        self.assertEqual(house(359, 0), 12)
        self.assertEqual(house(0, 11), 2)
        self.assertEqual(house(30, 1), 1)

    def test_aspect_orb_and_wraparound(self):
        self.assertEqual(aspects({'a': 359, 'b': 1})[0]['type'], 'соединение')
        self.assertEqual(aspects({'a': 0, 'b': 93})[0]['orb'], 3)
        self.assertEqual(aspects({'a': 0, 'b': 94}), [])
        self.assertEqual(aspects({'a': 0, 'b': 180})[0]['type'], 'оппозиция')

    def test_basis_must_match_calculated_house(self):
        sky = {'sign_context': {s: {'solar_whole_sign_houses': {'Луна': {'house': 2}}} for s in SIGNS}}
        result = {'basis': {s: {'body': 'Луна', 'house': 2, 'interpretation': 'Образ денег'} for s in SIGNS}}
        validate_basis(result, sky)
        result['basis']['Овен']['house'] = 9
        with self.assertRaises(ValueError):
            validate_basis(result, sky)
