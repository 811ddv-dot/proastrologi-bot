import unittest
from datetime import date
from mail_preview import parse_source, validate, fetch_sources
from mail_preview import apply_editor_changes, SLUGS, edit_summary, EDITOR_VERSION
from types import SimpleNamespace
from unittest.mock import patch


class MailPreviewTests(unittest.TestCase):
    def test_correct_fragment_preserves_other_signs(self):
        texts = dict.fromkeys(SLUGS, 'Удачное предложение.')
        texts['Стрелец'] = 'Возможны открытия, без спешки с выводами.'
        change = {'sign': 'Стрелец', 'before': ', без спешки с выводами',
                  'after': ', но с выводами лучше не торопиться',
                  'reason': 'Обрывок без грамматической связи', 'source_supported': True}
        review = {'checked': list(SLUGS), 'changes': [change], 'unresolved': []}
        fixed = apply_editor_changes(texts, review)
        self.assertEqual(fixed['Стрелец'], 'Возможны открытия, но с выводами лучше не торопиться.')
        self.assertEqual(fixed['Овен'], texts['Овен'])
        self.assertIn('без спешки', texts['Стрелец'])
        change['before'] = 'Несуществующий фрагмент'
        with self.assertRaises(ValueError):
            apply_editor_changes(texts, review)

    def test_incomplete_review_fails(self):
        with self.assertRaises(ValueError):
            apply_editor_changes(dict.fromkeys(SLUGS, 'Текст.'),
                                 {'checked': ['Овен'], 'changes': [], 'unresolved': []})

    def test_known_fragment_cannot_pass_empty_review(self):
        with self.assertRaises(ValueError):
            apply_editor_changes(dict.fromkeys(SLUGS, 'Открытия, без спешки с выводами.'),
                                 {'checked': list(SLUGS), 'changes': [], 'unresolved': []})

    def test_completed_editor_not_charged_twice(self):
        store = SimpleNamespace(data={'language_editor_version': EDITOR_VERSION})
        with patch('mail_preview.bot.model_json') as request:
            edit_summary(store, None, date(2026, 9, 26))
            request.assert_not_called()

    def test_extract_only_article(self):
        text = ' '.join(['слово'] * 65)
        raw = f'Прогноз на 26 сентября<p>Реклама</p><main itemProp="articleBody"><p>{text}</p></main><p>Другое</p>'
        self.assertEqual(parse_source(raw, date(2026, 9, 26)), text)

    def test_wrong_date_rejected(self):
        with self.assertRaises(ValueError):
            parse_source('Прогноз на 25 сентября', date(2026, 9, 26))

    def test_missing_article_rejected(self):
        with self.assertRaises(ValueError):
            parse_source('Прогноз на 26 сентября<p>Меню</p>', date(2026, 9, 26))

    def test_missing_signs_rejected(self):
        with self.assertRaises(ValueError):
            validate({'forecasts': {}}, {})

    def test_old_date_not_relabelled(self):
        with self.assertRaises(ValueError):
            fetch_sources(date(2000, 1, 1))
