"""Validate the reviewer's evidence before asking the writer to repair text."""

KINDS = {'duplicate', 'language', 'tautology', 'incoherent'}


def verified_issues(review, edition, history, changed=None):
    if not isinstance(review, dict) or not isinstance(review.get('issues'), dict):
        raise ValueError('Нужен объект issues.')
    issues = review['issues']
    checked = {}
    errors = []
    for sign, issue in issues.items():
        try:
            target, note = verify_issue(sign, issue, edition, history, changed)
            checked.setdefault(target, []).append(note)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError('\n'.join(errors))
    return checked


def verify_issue(sign, issue, edition, history, changed):
        if sign not in edition or not isinstance(issue, dict):
            raise ValueError('Неизвестный знак или неверный формат замечания.')
        kind = issue.get('kind')
        quote = issue.get('quote')
        if kind not in KINDS or not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in edition[sign]:
            raise ValueError(f'{sign}: неверный kind или неточная цитата. Реальный проверяемый абзац: {edition[sign]}')
        if not isinstance(issue.get('reason'), str) or not issue['reason'].strip():
            raise ValueError(f'{sign}: нет объяснения нарушения.')
        target = sign
        note = dict(issue)
        if kind == 'duplicate':
            ref = issue.get('reference')
            if not isinstance(ref, dict):
                raise ValueError(f'{sign}: у повтора нет ссылки на другой текст.')
            other_sign, day = ref.get('sign'), ref.get('date')
            if day == 'current':
                source = edition.get(other_sign)
                if other_sign == sign:
                    raise ValueError('Нельзя сравнивать абзац с самим собой.')
            else:
                source = next((item.get('forecasts', {}).get(other_sign)
                               for item in history if item.get('date') == day), None)
            other_quote = ref.get('quote')
            if (not isinstance(source, str) or not isinstance(other_quote, str)
                    or len(other_quote.strip()) < 8 or other_quote not in source):
                raise ValueError(f'{sign}: неверная ссылка или неточная цитата ({day}, {other_sign}). '
                                 f'Реальный текст этого источника: {source!r}. '
                                 'Процитируй его дословно, выбери настоящий источник или отзови неподтверждённое замечание.')
            # When an edited paragraph collides with a frozen one, repair the edited one.
            if changed is not None and sign not in changed and day == 'current' and other_sign in changed:
                target = other_sign
                note = {**issue, 'quote': other_quote,
                        'reference': {'date': 'current', 'sign': sign, 'quote': quote}}
        if changed is not None and target not in changed:
            raise ValueError(f'{sign}: абзац уже проверен и не менялся; проверяй исправления и новые пересечения.')
        return target, note
