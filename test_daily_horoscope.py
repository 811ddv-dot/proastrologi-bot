import copy
import contextlib
import io
import json
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
    def test_history_retains_thirty_editions(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'history.json'
            entries = [{'date': f'2026-08-{day:02d}', 'forecasts': {}}
                       for day in range(1, 32)]
            state.write_text(json.dumps(entries), encoding='utf-8')
            with patch.object(bot, 'STATE', state):
                self.assertEqual(bot.HISTORY_LIMIT, 30)
                self.assertEqual(bot.read_history(), entries[1:])
                latest = {'date': '2026-09-01', 'forecasts': {}}
                bot.remember(latest)
                self.assertEqual(bot.read_history(), entries[2:] + [latest])
                self.assertEqual(len(json.loads(state.read_text())), 30)

    def test_one_post_contains_all_signs_and_single_date(self):
        edition = {sign: 'Текст & смысл.' for sign in bot.SIGNS}
        post = bot.format_edition(date(2026, 9, 21), edition)
        self.assertEqual(post.count('21 сентября'), 1)
        self.assertEqual(post.count('<b>'), 13)
        self.assertIn('Текст &amp; смысл.', post)
        for sign in bot.SIGNS:
            self.assertEqual(post.count(sign.upper()), 1)

    def test_max_sign_lengths_fit_even_long_month(self):
        edition = {sign: 'а' * bot.MAX_SIGN_LENGTH for sign in bot.SIGNS}
        post = bot.format_edition(date(2026, 9, 30), edition, markup=False)
        self.assertLessEqual(bot.text_length(post), bot.TELEGRAM_LIMIT)

    def test_total_length_boundary_and_utf16(self):
        edition = {sign: 'а' for sign in bot.SIGNS}
        count = bot.text_length(bot.format_edition(date(2026, 9, 21), edition, markup=False))
        edition['Овен'] += 'а' * (4096 - count)
        self.assertEqual(bot.text_length(bot.format_edition(date(2026, 9, 21), edition, markup=False)), 4096)
        edition['Овен'] += 'а'
        with self.assertRaises(ValueError):
            bot.format_edition(date(2026, 9, 21), edition)
        self.assertEqual(bot.text_length('🌟'), 2)

    def test_publish_sends_once_then_remembers(self):
        bundle = {'date': '2026-09-21', 'forecasts': {sign: 'Готовый абзац.' for sign in bot.SIGNS}}
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test'}), \
                patch.object(bot, 'request_json', return_value={'ok': True, 'result': {'message_id': 42}}) as send, \
                patch.object(bot, 'remember') as remember:
            bot.publish_bundle(date(2026, 9, 21), bundle)
        send.assert_called_once()
        remember.assert_called_once_with(bundle)
        self.assertEqual(send.call_args.args[1]['text'].count('<b>'), 13)

    def test_invalid_post_never_sent(self):
        for edition in ({'Овен': 'Текст.'}, {sign: 'а' * 500 for sign in bot.SIGNS}):
            with patch.object(bot, 'request_json') as send, patch.object(bot, 'remember') as remember:
                with self.assertRaises(ValueError):
                    bot.publish_bundle(date(2026, 9, 21), {'forecasts': edition})
                send.assert_not_called()
                remember.assert_not_called()

    def test_failed_send_not_retried_or_remembered(self):
        bundle = {'forecasts': {sign: 'Текст.' for sign in bot.SIGNS}}
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test'}), \
                patch.object(bot, 'request_json', return_value={'ok': False}) as send, \
                patch.object(bot, 'remember') as remember:
            with self.assertRaises(RuntimeError):
                bot.publish_bundle(date(2026, 9, 21), bundle)
            send.assert_called_once()
            remember.assert_not_called()

    def test_compact_paragraph_limits(self):
        body = ('Сегодня станет проще вернуться к делу, которое долго не двигалось с места. '
                'Чужой опыт поможет заметить удачное решение и избежать лишней спешки. '
                'Не берите на себя новые обещания, пока не закончите начатое.')
        bot.validate({'Овен': body}, require_all=False)
        with self.assertRaises(ValueError):
            bot.validate({'Овен': body + ' Оченьдлинно' * 15}, require_all=False)

    def test_selected_model_is_sent_and_usage_contains_no_key(self):
        response = {'model': 'gpt-5.4', 'usage': {'prompt_tokens': 100, 'completion_tokens': 20},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        output = io.StringIO()
        with patch.object(bot, 'request_json', return_value=response) as request, \
                contextlib.redirect_stderr(output):
            bot.model_json('SECRET_TEST_KEY', 'gpt-5.4', 'instruction', {})
        self.assertEqual(request.call_args.args[1]['model'], 'gpt-5.4')
        self.assertIn('API_USAGE', output.getvalue())
        self.assertNotIn('SECRET_TEST_KEY', output.getvalue())

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
                patch.object(bot, 'model_json', side_effect=[plan, edition] + [edition] * bot.EDITORIAL_ATTEMPTS):
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
                    {'issues': {'Рак': {'kind': 'duplicate', 'quote': 'original Рак',
                                       'reason': 'Совпала ситуация и итог.',
                                       'reference': {'date': 'current', 'sign': 'Овен', 'quote': 'original Овен'}}}},
                    revised, {'issues': {}}]):
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
