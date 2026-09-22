import base64
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import daily_horoscope as bot
import text_archive as archive
from generation_store import GenerationStore
from test_generation_store import FakeRepository
from editorial_review import full_source_review


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 9, 26)
        self.published = [{'date': '2026-09-24', 'forecasts': {'Овен': 'Опубликованный текст.'}}]

    def journal(self, day='2026-09-25'):
        return {'date': day, 'responses': {
            'a': {'Овен': 'Первый черновик.', 'Рак': 'Опубликованный текст.'},
            'b': {'Овен': 'Второй черновик.'},
            'c': {'issues': {}, 'Овен': {'domain': 'работа'}}}}

    def test_keeps_all_variants_and_deduplicates_published(self):
        result = archive.build_archive(self.day, self.published,
            [('generation-state/2026-09-25.json', self.journal())], bot.SIGNS)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]['forecasts'], {'Овен': 'Первый черновик.'})
        self.assertNotEqual(result[1]['date'], result[2]['date'])

    def test_current_future_and_expired_drafts_excluded(self):
        journals = [(f'generation-state/{d}.json', self.journal(d))
                    for d in ('2026-09-26', '2026-09-27', '2026-08-26')]
        self.assertEqual(archive.build_archive(self.day, self.published, journals, bot.SIGNS), self.published)

    def test_draft_reference_binds_correct_variant(self):
        history = archive.build_archive(self.day, [], [('x', self.journal())], bot.SIGNS)
        result = full_source_review({'issues': {'Телец': {'kind': 'duplicate',
            'reference': {'date': history[1]['date'], 'sign': 'Овен'}}}},
            {'Телец': 'Текущий текст.'}, history)
        self.assertEqual(result['issues']['Телец']['reference']['quote'], 'Второй черновик.')

    def test_snapshot_persists_and_restart_does_not_reload_archive(self):
        repo = FakeRepository()
        path = 'generation-state/2026-09-25-continuation-1.json'
        repo.files[path] = {'sha': 'old', 'content': base64.b64encode(json.dumps(self.journal()).encode()).decode()}
        def api(method, payload=None, path=None):
            if method == 'GET' and path == 'generation-state':
                return [{'path': p} for p in repo.files]
            return repo(method, payload, path)
        store = GenerationStore(self.day, api)
        with tempfile.TemporaryDirectory() as tmp, patch.object(archive, 'ARCHIVE_FILE', Path(tmp) / 'archive.json'):
            original = archive.history_for_generation(self.day, self.published, store, bot.SIGNS)
            restarted = GenerationStore(self.day, api)
            with patch.object(restarted, 'api', side_effect=AssertionError('No reads or writes')):
                self.assertEqual(original, archive.history_for_generation(self.day, [], restarted, bot.SIGNS))
            self.assertEqual(json.loads(archive.ARCHIVE_FILE.read_text()), original)

    def test_old_paid_journal_not_silently_regenerated(self):
        store = GenerationStore(self.day, FakeRepository())
        store.data['responses'] = {'old': {'Овен': 'Текст'}}
        with self.assertRaisesRegex(RuntimeError, 'повторная платная'):
            archive.history_for_generation(self.day, [], store, bot.SIGNS)

    def test_repair_keeps_more_than_30_variant_entries(self):
        history = [{'date': str(i), 'forecasts': {'Овен': str(i)}} for i in range(40)]
        payload = bot.repair_payload(self.day, {}, {}, {}, [], history)
        self.assertEqual(len(payload['history']), 40)

    def test_archive_failure_stops_before_model_call(self):
        store = GenerationStore(self.day, FakeRepository())
        with patch.object(store, 'api', side_effect=RuntimeError('archive unavailable')), \
             patch.object(bot, 'GENERATION_STORE', store), \
             patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-test'}), \
             patch.object(bot, 'model_json') as model:
            with self.assertRaisesRegex(RuntimeError, 'archive unavailable'):
                bot.generate_bundle(self.day, [])
            model.assert_not_called()
