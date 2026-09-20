import copy
import contextlib
import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import daily_horoscope as bot


def sample_plan():
    # Deliberately distinct tokens: these fixtures test contracts, not literary quality.
    labels = 'встреча отдых учёба дружба семья деньги работа свобода поездка выбор успех терпение'.split()
    return {sign: {'domain': bot.DOMAINS[i % 8], 'mood': bot.MOODS[i % 4],
                   'situation': labels[i], 'turn': labels[i] + ' развитие',
                   'ending': labels[i] + ' итог'}
            for i, sign in enumerate(bot.SIGNS)}


class EditorialTests(unittest.TestCase):
    def test_truncated_model_output_has_one_bounded_retry(self):
        truncated = {'choices': [{'finish_reason': 'length'}]}
        complete = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        with patch.object(bot, 'request_json', side_effect=[truncated, complete]) as request:
            self.assertEqual(bot.model_json('test', 'gpt-5-mini', 'instruction', {}), {})
            self.assertEqual(request.call_args_list[1].args[1]['max_completion_tokens'], 24000)
        with patch.object(bot, 'request_json', return_value=truncated) as request:
            with self.assertRaises(ValueError):
                bot.model_json('test', 'gpt-5-mini', 'instruction', {})
            self.assertEqual(request.call_count, 2)

    def test_plan_needs_all_signs(self):
        plan = sample_plan()
        plan.pop('Овен')
        with self.assertRaises(ValueError):
            bot.validate_plan(plan, [])

    def test_plan_diversity(self):
        bot.validate_plan(sample_plan(), [])
        for field, value in [('mood', bot.MOODS[0]), ('domain', bot.DOMAINS[0])]:
            plan = sample_plan()
            for item in plan.values():
                item[field] = value
            with self.assertRaises(ValueError):
                bot.validate_plan(plan, [])

    def test_plan_history_repetition_rejected(self):
        plan = sample_plan()
        with self.assertRaisesRegex(ValueError, 'повторяет'):
            bot.validate_plan(plan, [{'date': '2026-09-20', 'plan': plan}])

    def test_separate_planning_writing_and_language_editor(self):
        plan = sample_plan()
        draft = {sign: 'draft' for sign in bot.SIGNS}
        edited = {sign: 'edited' for sign in bot.SIGNS}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'validate'), patch.object(bot, 'validate_originality'), \
                patch.object(bot, 'validate_language'), \
                patch.object(bot, 'model_json', side_effect=[plan, draft, edited, {'issues': {}}]) as model:
            result = bot.generate_bundle(date(2026, 9, 21), [])
        self.assertEqual(result['forecasts'], edited)
        self.assertEqual(result['plan'], plan)
        self.assertEqual(model.call_args_list[0].args[2], bot.PLAN_PROMPT)
        self.assertEqual(model.call_args_list[1].args[2], bot.WRITE_PROMPT)
        self.assertEqual(model.call_args_list[2].args[2], bot.LANGUAGE_PROMPT)
        self.assertEqual(model.call_args_list[2].args[3]['edition'], draft)

    def test_bad_language_retried_without_replanning(self):
        plan = sample_plan()
        edition = {sign: 'text' for sign in bot.SIGNS}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'validate'), patch.object(bot, 'validate_originality'), \
                patch.object(bot, 'edition_issues', side_effect=[{'Овен': ['канцеляризм']}, {}]), \
                patch.object(bot, 'model_json', side_effect=[plan, edition, edition, edition, {'issues': {}}]) as model:
            bot.generate_bundle(date(2026, 9, 21), [])
        self.assertEqual(model.call_count, 5)
        self.assertIn('канцеляризм', model.call_args_list[3].args[3]['validation_error']['Овен'])

    def test_failed_edit_never_returns_bundle(self):
        plan = sample_plan()
        edition = {sign: 'text' for sign in bot.SIGNS}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'edition_issues', return_value={'Овен': ['неверный текст']}), \
                patch.object(bot, 'model_json', side_effect=[plan, edition, edition, edition, edition]):
            with self.assertRaisesRegex(RuntimeError, 'Ничего не опубликовано'):
                bot.generate_bundle(date(2026, 9, 21), [])

    def test_repair_preserves_other_signs_even_if_model_changes_them(self):
        edition = {sign: 'original ' + sign for sign in bot.SIGNS}
        changed = {sign: 'changed ' + sign for sign in bot.SIGNS}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'edition_issues', side_effect=[{'Овен': ['length']}, {}]), \
                patch.object(bot, 'model_json', side_effect=[sample_plan(), edition, edition, changed, {'issues': {}}]):
            result = bot.generate_bundle(date(2026, 9, 21), [])['forecasts']
        self.assertEqual(result['Овен'], changed['Овен'])
        for sign in set(bot.SIGNS) - {'Овен'}:
            self.assertEqual(result[sign], edition[sign])

    def test_all_invalid_signs_are_reported_together(self):
        edition = {sign: 'Слишком коротко.' for sign in bot.SIGNS}
        self.assertEqual(set(bot.edition_issues(edition, [])), set(bot.SIGNS))

    def test_semantic_repetition_is_repaired(self):
        edition = {sign: 'original ' + sign for sign in bot.SIGNS}
        revised = {**edition, 'Рак': 'новая тема'}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'edition_issues', return_value={}), \
                patch.object(bot, 'model_json', side_effect=[sample_plan(), edition, edition,
                    {'issues': {'Рак': 'Повторён вчерашний смысл'}}, revised, {'issues': {}}]):
            result = bot.generate_bundle(date(2026, 9, 21), [])
        self.assertEqual(result['forecasts']['Рак'], 'новая тема')

    def test_same_domain_as_previous_day_is_rejected(self):
        plan = sample_plan()
        past = copy.deepcopy(plan)
        for item in past.values():
            item.update(situation='прошлое', turn='другое', ending='отдельное')
        with self.assertRaisesRegex(ValueError, 'смени основную сферу'):
            bot.validate_plan(plan, [{'date': '2026-09-20', 'plan': past}])

    def test_jargon_and_example_copy_rejected(self):
        with self.assertRaises(ValueError):
            bot.validate_language({'Овен': 'Коммуникация требует структурирования.'})
        with self.assertRaises(ValueError):
            bot.validate_language({'Овен': bot.EXAMPLES[0]})

    def test_three_day_preview_uses_history_without_publishing(self):
        seen = []
        def generate(day, history):
            seen.append(copy.deepcopy(history))
            return {'date': day.isoformat(), 'plan': sample_plan(),
                    'forecasts': {sign: str(day) + sign for sign in bot.SIGNS}}
        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            try:
                os.chdir(folder)
                state = Path(folder) / 'production-history.json'
                state.write_text('[]')
                with patch.object(bot, 'STATE', state), patch.object(bot, 'generate_bundle', side_effect=generate), \
                        patch.object(bot, 'remember') as remember, patch.object(bot, 'request_json') as network:
                    with contextlib.redirect_stdout(io.StringIO()):
                        bundles = bot.preview_sequence(date(2026, 9, 21), 3)
                self.assertEqual([len(x) for x in seen], [0, 1, 2])
                self.assertEqual(seen[2][-1]['date'], '2026-09-22')
                self.assertEqual(state.read_text(), '[]')
                self.assertEqual(len(bundles), 3)
                self.assertTrue(Path('preview.md').exists())
                self.assertTrue(Path('preview-report.md').exists())
                remember.assert_not_called()
                network.assert_not_called()
            finally:
                os.chdir(previous)

    def test_verbatim_history_rejected(self):
        edition = {sign: 'договорённости изменились и стоит обсудить условия снова ' + sign
                   for sign in bot.SIGNS}
        with self.assertRaises(ValueError):
            bot.validate_originality(edition, [{'date': '2026-09-20', 'forecasts': edition}])


if __name__ == '__main__':
    unittest.main()
