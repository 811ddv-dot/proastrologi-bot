import unittest
from datetime import date
from mail_preview import parse_source, validate, fetch_sources


class MailPreviewTests(unittest.TestCase):
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
