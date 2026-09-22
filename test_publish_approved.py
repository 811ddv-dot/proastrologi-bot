import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import publish_approved as approved


class ApprovedPublicationTests(unittest.TestCase):
    def test_stale_date_never_publishes(self):
        with patch.object(approved.bot, 'publish_bundle') as send:
            with self.assertRaises(ValueError):
                approved.publish_saved(Path('unused'), date(2026, 9, 21))
            send.assert_not_called()

    def test_already_published_never_sends(self):
        with patch.object(approved.bot, 'read_history', return_value=[{'date': approved.APPROVED_DATE.isoformat()}]), \
                patch.object(approved.bot, 'publish_bundle') as send:
            self.assertFalse(approved.publish_saved(Path('unused'), approved.APPROVED_DATE))
            send.assert_not_called()

    def test_only_identical_saved_text_is_published(self):
        day = approved.APPROVED_DATE
        bundle = {'date': day.isoformat(), 'forecasts': {sign: 'Текст.' for sign in approved.bot.SIGNS}}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            datafile = folder / 'preview-data.json'
            datafile.write_text(json.dumps([{'date': '2026-09-23'}, bundle, {'date': '2026-09-24'}]))
            postfile = folder / f'preview-post-{day}.html'
            postfile.write_text(approved.bot.format_edition(day, bundle['forecasts']))
            with patch.object(approved.bot, 'read_history', return_value=[]), \
                    patch.object(approved.bot, 'validate'), patch.object(approved.bot, 'validate_language'), \
                    patch.object(approved.bot, 'publish_bundle') as send:
                self.assertTrue(approved.publish_saved(folder, day))
                send.assert_called_once_with(day, bundle)
                send.reset_mock()
                datafile.write_text(json.dumps([bundle, bundle]))
                with self.assertRaises(ValueError):
                    approved.publish_saved(folder, day)
                send.assert_not_called()
                datafile.write_text(json.dumps([{'date': '2026-09-23'}]))
                with self.assertRaises(ValueError):
                    approved.publish_saved(folder, day)
                send.assert_not_called()
                datafile.write_text(json.dumps([bundle]))
                postfile.write_text('Изменённый текст')
                with self.assertRaises(ValueError):
                    approved.publish_saved(folder, day)
                send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
