"""Validate the reviewer's evidence before asking the writer to repair text."""
import re

KINDS = {'duplicate', 'language', 'tautology', 'incoherent'}


def grounded_quote(source, quote):
    """Recover literal source spans from excerpts with omissions, never paraphrases."""
    if not isinstance(source, str) or not isinstance(quote, str) or len(quote.strip()) < 8:
        return None
    if quote in source:
        return quote
    source_words = list(re.finditer(r'\w+', source))
    quoted_words = re.findall(r'\w+', quote)
    if len(quoted_words) < 6:
        return None
    for start, word in enumerate(source_words):
        if word.group() != quoted_words[0]:
            continue
        cursor = start
        for token in quoted_words[1:]:
            found = next((i for i in range(cursor + 1, len(source_words))
                          if source_words[i].group() == token), None)
            if found is None:
                break
            cursor = found
        else:
            # At least 65% of the recovered span must have been quoted verbatim.
            if len(quoted_words) / (cursor - start + 1) >= 0.65:
                return source[source_words[start].start():source_words[cursor].end()]
    return None


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
        quote = grounded_quote(edition[sign], issue.get('quote'))
        if kind not in KINDS or quote is None:
            raise ValueError(f'{sign}: неверный kind или неточная цитата. Реальный проверяемый абзац: {edition[sign]}')
        if not isinstance(issue.get('reason'), str) or not issue['reason'].strip():
            raise ValueError(f'{sign}: нет объяснения нарушения.')
        target = sign
        note = {**issue, 'quote': quote}
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
            grounded = grounded_quote(source, other_quote)
            if (isinstance(other_quote, str) and len(other_quote.strip()) >= 8
                    and grounded is None):
                sources = [('current', name, body) for name, body in edition.items() if name != sign]
                sources.extend((item['date'], name, body) for item in history
                               for name, body in item.get('forecasts', {}).items())
                matches = [(date, name, body) for date, name, body in sources
                           if grounded_quote(body, other_quote) is not None]
                if len(matches) == 1:
                    day, other_sign, source = matches[0]
                    grounded = grounded_quote(source, other_quote)
            if grounded is None:
                raise ValueError(f'{sign}: неверная ссылка или неточная цитата ({day}, {other_sign}). '
                                 f'Реальный текст этого источника: {source!r}. '
                                 f'Указанная цитата: {other_quote!r}. '
                                 'Процитируй его дословно, выбери настоящий источник или отзови неподтверждённое замечание.')
            other_quote = grounded
            note['reference'] = {'date': day, 'sign': other_sign, 'quote': other_quote}
            # When an edited paragraph collides with a frozen one, repair the edited one.
            if changed is not None and sign not in changed and day == 'current' and other_sign in changed:
                target = other_sign
                note = {**issue, 'quote': other_quote,
                        'reference': {'date': 'current', 'sign': sign, 'quote': quote}}
        if changed is not None and target not in changed:
            raise ValueError(f'{sign}: абзац уже проверен и не менялся; проверяй исправления и новые пересечения.')
        return target, note
