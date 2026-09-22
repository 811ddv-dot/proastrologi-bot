import unittest
from unittest.mock import patch
import continue_preview as continuation
import daily_horoscope as bot


class ContinuationTests(unittest.TestCase):
    def test_only_two_signs_change(self):
        source = {s: s for s in bot.SIGNS}
        result = continuation.merge_targets(source, {'Овен': 'new', 'Рак': 'new'}, continuation.TARGETS)
        for s in set(bot.SIGNS) - continuation.TARGETS:
            self.assertEqual(result[s], source[s])

    def test_extra_signs_rejected(self):
        with self.assertRaises(ValueError):
            continuation.merge_targets({}, {'Овен': 'x', 'Рак': 'x', 'Лев': 'x'}, continuation.TARGETS)

    def test_wrong_source_stops_before_api(self):
        with patch('history_store.api', return_value={'sha': 'wrong'}), patch.object(bot, 'model_json') as paid:
            with self.assertRaises(RuntimeError):
                continuation.run()
            paid.assert_not_called()
