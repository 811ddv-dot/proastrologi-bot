import unittest
from unittest.mock import patch

import daily_horoscope as bot
from editorial_review import verified_issues, grounded_quote


class EvidenceTests(unittest.TestCase):
    def test_recovers_omitted_source_words_without_inventing(self):
        source = ('Подход, казавшийся слишком смелым, встретит молчаливое одобрение '
                  'и перестанет выглядеть странно. После этого будет легче действовать.')
        quote = ('Подход, казавшийся слишком смелым, встретит молчаливое одобрение. '
                 'После этого будет легче действовать.')
        result = grounded_quote(source, quote)
        self.assertIsNotNone(result)
        self.assertIn(result, source)
        self.assertIn('и перестанет выглядеть странно', result)
        self.assertIsNone(grounded_quote(source, quote.replace('молчаливое', 'бурное')))

    def test_sparse_word_salad_is_not_a_quote(self):
        source = 'один а б в г два д е ё ж три з и й к четыре л м н о пять п р с т шесть'
        self.assertIsNone(grounded_quote(source, 'один два три четыре пять шесть'))

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
        result = verified_issues({'issues': {'Овен': self.issue}}, self.edition, history)
        self.assertEqual(result['Овен'][0]['reference']['date'], '2026-09-21')

    def test_recovers_unique_historical_quote_mislabeled_current(self):
        self.issue['reference'] = {'date': 'current', 'sign': 'Весы', 'quote': 'Лёгкое общение помогает отдохнуть'}
        history = [{'date': '2026-09-22', 'forecasts': {'Весы': 'Лёгкое общение помогает отдохнуть от забот.'}}]
        result = verified_issues({'issues': {'Овен': self.issue}}, self.edition, history)
        self.assertEqual(result['Овен'][0]['reference']['date'], '2026-09-22')

    def test_ambiguous_quote_cannot_repair_wrong_reference(self):
        self.issue['reference'] = {'date': 'current', 'sign': 'Весы', 'quote': 'Лёгкое общение помогает отдохнуть'}
        history = [{'date': '2026-09-22', 'forecasts': {
            'Весы': 'Лёгкое общение помогает отдохнуть от забот.',
            'Рак': 'Лёгкое общение помогает отдохнуть и сменить настрой.'}}]
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
        with patch.object(bot, 'model_json', side_effect=[{'issues': {'Овен': self.issue}}, {'confirmed': ['Овен']}]) as model:
            result = bot.review_edition('key', 'model', self.edition, [],
                                        dict(self.edition), {'Овен': [self.issue]})
            self.assertIn('Овен', result)
            self.assertEqual(model.call_args_list[0].args[3]['review_signs'], ['Овен'])

    def test_initial_review_covers_every_sign(self):
        with patch.object(bot, 'model_json', return_value={'issues': {}}) as model:
            bot.review_edition('key', 'model', self.edition, [])
            self.assertEqual(set(model.call_args.args[3]['review_signs']), set(bot.SIGNS))

    def test_planner_and_reviewer_enable_reasoning(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        for instruction in (bot.PLAN_PROMPT, bot.QUALITY_PROMPT, bot.LANGUAGE_PROMPT, bot.ADJUDICATE_PROMPT, bot.WRITE_PROMPT):
            with patch.object(bot, 'API_BUDGET', bot.RequestBudget()), patch.object(bot, 'request_json', return_value=response) as request:
                bot.model_json('key', 'gpt-5.4', instruction, {})
                payload = request.call_args.args[1]
                if instruction == bot.WRITE_PROMPT:
                    self.assertNotIn('reasoning_effort', payload)
                else:
                    self.assertEqual(payload['reasoning_effort'], 'low')

    def test_reports_all_bad_evidence_at_once(self):
        issue = {'kind': 'language', 'quote': 'Выдуманная цитата', 'reason': 'Ошибка.'}
        with self.assertRaises(ValueError) as error:
            verified_issues({'issues': {'Овен': issue, 'Телец': issue}}, self.edition, [])
        self.assertIn(self.edition['Овен'], str(error.exception))
        self.assertIn(self.edition['Телец'], str(error.exception))

    def test_review_history_excludes_stale_plans(self):
        history = [{'date': '2026-09-21', 'forecasts': self.edition, 'plan': {'stale': 'plan'}}]
        with patch.object(bot, 'model_json', return_value={'issues': {}}) as model:
            bot.review_edition('key', 'model', self.edition, history)
            self.assertNotIn('plan', model.call_args.args[3]['history'][0])

    def test_format_repairs_do_not_spend_content_budget(self):
        from datetime import date
        from test_daily_horoscope import sample_plan
        edition = dict(self.edition)
        # One formatting failure plus one semantic failure must still allow success.
        checks = [{'Овен': ['length']}, {}, {}]
        issue = {'Овен': [{'kind': 'language', 'quote': edition['Овен'], 'reason': 'Ошибка'}]}
        with patch.dict(bot.os.environ, {'OPENAI_API_KEY': 'test'}), \
                patch.object(bot, 'model_json', side_effect=[sample_plan(), edition] + [edition] * 7), \
                patch.object(bot, 'edition_issues', side_effect=checks), \
                patch.object(bot, 'review_edition', side_effect=[issue, {}]):
            self.assertEqual(bot.generate_bundle(date(2026, 9, 22), [])['forecasts'], edition)

    def test_maximum_paragraphs_fit_one_post_in_every_month(self):
        from datetime import date
        edition = {sign: 'а' * bot.MAX_SIGN_LENGTH for sign in bot.SIGNS}
        for month in range(1, 13):
            post = bot.format_edition(date(2026, month, 28), edition, markup=False)
            self.assertLessEqual(bot.text_length(post), bot.TELEGRAM_LIMIT)

    def test_unconfirmed_claim_does_not_block_edition(self):
        self.issue['quote'] = 'Искажённый пересказ'
        self.issue['reference']['quote'] = 'Выдуманная цитата'
        with patch.object(bot, 'model_json', side_effect=[{'issues': {'Овен': self.issue}}, {'confirmed': []}]) as model:
            self.assertEqual(bot.review_edition('key', 'model', self.edition, []), {})
            candidate = model.call_args.args[3]['candidates']['Овен'][0]
            self.assertEqual(candidate['quote'], self.edition['Овен'])
            self.assertEqual(candidate['reference']['quote'], self.edition['Телец'])

    def test_confirmed_claim_requires_repair(self):
        with patch.object(bot, 'model_json', side_effect=[{'issues': {'Овен': self.issue}}, {'confirmed': ['Овен']}]):
            self.assertIn('Овен', bot.review_edition('key', 'model', self.edition, []))

    def test_malformed_independent_verdict_fails_closed(self):
        replies = [{'issues': {'Овен': self.issue}}, {'confirmed': ['Unknown']}] * 2
        with patch.object(bot, 'model_json', side_effect=replies):
            with self.assertRaises(RuntimeError):
                bot.review_edition('key', 'model', self.edition, [])


if __name__ == '__main__':
    unittest.main()
