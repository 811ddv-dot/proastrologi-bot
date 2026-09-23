"""Budget-bound editing; quality warnings may be waived, structural errors may not."""
from copy import deepcopy


def edit_with_budget(bot, day, key, model, plan, draft, payload, history):
    edition = draft
    targets = None
    feedback = []
    previous = previous_issues = None
    fallback = None
    rounds = 0
    repaired_signs = 0
    costs = []
    reason = 'passed'
    while True:
        before = bot.API_BUDGET.spent
        try:
            candidate = bot.clean_labels(bot.model_json(
                key, model, bot.REPAIR_PROMPT if targets else bot.LANGUAGE_PROMPT, payload))
            if targets:
                rounds += 1
                repaired_signs += len(targets)
                if isinstance(candidate, dict):
                    edition = {s: candidate.get(s, edition.get(s)) if s in targets
                               else edition[s] for s in bot.SIGNS}
                else:
                    raise ValueError('Редактор вернул не объект.')
            else:
                edition = candidate
            # Always retain the last complete, Telegram-compatible edition.
            try:
                bot.format_edition(day, edition)
            except (ValueError, TypeError, KeyError):
                pass
            else:
                fallback = (deepcopy(edition), None)
            issues = bot.edition_issues(edition, history)
            if not issues:
                issues = bot.review_edition(key, model, edition, history, previous, previous_issues)
                previous, previous_issues = deepcopy(edition), deepcopy(issues)
            if fallback and fallback[0] == edition:
                fallback = (deepcopy(edition), deepcopy(issues))
            if targets:
                costs.append(max(0, bot.API_BUDGET.spent - before))
            if not issues:
                break
            targets = set(issues)
            payload = bot.repair_payload(day, plan, edition, issues, feedback, history)
            feedback.append(issues)
            # Distinguish subsequent attempts even when the model repeats a response.
            payload['budget_revision'] = rounds + 1
            print(f'Доработок: {rounds}; осталось знаков: {len(issues)}; бюджет: ${bot.API_BUDGET.spent:.5f}/1.00', flush=True)
        except bot.BudgetExhausted:
            if fallback is None:
                raise RuntimeError('Бюджет исчерпан, полного пригодного поста нет; публикация запрещена.')
            edition, issues = fallback
            reason = 'budget'
            break
    report = {'date': str(day), 'reason': reason, 'repair_rounds': rounds,
              'sign_rewrites': repaired_signs, 'spent_usd_estimate': bot.API_BUDGET.spent,
              'budget_usd': bot.API_BUDGET.limit, 'remaining_issues': issues,
              'remaining_signs': None if issues is None else len(issues),
              'next_round_usd_estimate': (sum(costs) / len(costs)) if costs and issues else None}
    bundle = {'date': str(day), 'forecasts': edition, 'editorial_report': report}
    if not rounds:
        bundle['plan'] = plan
    if bot.GENERATION_STORE is not None:
        bot.GENERATION_STORE.data['editorial_report'] = report
        bot.GENERATION_STORE.save()
    return bundle


def report_text(report):
    if report.get('saved_preview'):
        return (f"Выпуск на {report['date']} опубликован из сохранённого проверенного текста.\n"
                f"Новых генераций и доработок: 0. Дополнительный расход: $0.\n"
                f"Расчётный расход на подготовку ранее: ${report['spent_usd_estimate']:.4f}.")
    remaining = report['remaining_signs']
    text = (f"Выпуск на {report['date']} опубликован.\n"
            f"Доработок: {report['repair_rounds']} раундов, {report['sign_rewrites']} переписываний знаков.\n"
            f"Расчётный расход: ${report['spent_usd_estimate']:.4f} / ${report['budget_usd']:.2f}.\n")
    if remaining is None:
        text += 'Бюджет остановил проверку. Число оставшихся замечаний неизвестно.\n'
    else:
        count = sum(len(v) for v in (report['remaining_issues'] or {}).values())
        text += f'Осталось: {count} замечаний у {remaining} знаков.\n'
        if remaining:
            text += 'Знаки: ' + ', '.join(report['remaining_issues']) + '.\n'
    estimate = report.get('next_round_usd_estimate')
    if estimate is not None:
        text += f'Ориентир ещё одного раунда с проверкой: ${estimate:.4f} (среднее прошлых раундов).\n'
    if remaining != 0:
        text += 'Точное число дополнительных попыток и итоговую стоимость заранее узнать нельзя. Опубликовано с замечаниями либо незавершённой проверкой.'
    else:
        text += 'Проверка пройдена; дополнительных доработок не требуется.'
    return text
