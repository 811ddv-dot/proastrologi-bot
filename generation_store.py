"""Durable, credential-free checkpoints for one edition, with ambiguous-call guards."""
import hashlib
import json


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class GenerationStore:
    def __init__(self, day, api):
        self.api = api
        self.path = f'generation-state/{day.isoformat()}.json'
        remote = api('GET', path=self.path)
        self.sha = None
        if remote is None:
            self.data = {'version': 1, 'date': day.isoformat(), 'calls': 0,
                         'spent': 0.0, 'responses': {}, 'pending': None}
        else:
            import base64
            self.sha = remote['sha']
            self.data = json.loads(base64.b64decode(remote['content']))
            if (self.data.get('version') != 1 or self.data.get('date') != day.isoformat()
                    or type(self.data.get('calls')) is not int or self.data['calls'] < 0
                    or not isinstance(self.data.get('spent'), (int, float))
                    or not 0 <= self.data['spent'] < 100
                    or not isinstance(self.data.get('responses'), dict)):
                raise ValueError('Повреждён журнал генерации; платные запросы заблокированы.')

    def save(self):
        import base64
        payload = {'message': f'Checkpoint horoscope {self.data["date"]}', 'branch': 'main',
                   'content': base64.b64encode(json.dumps(self.data, ensure_ascii=False).encode()).decode()}
        if self.sha:
            payload['sha'] = self.sha
        result = self.api('PUT', payload, path=self.path)
        self.sha = result['content']['sha']

    def cached(self, key):
        if key in self.data['responses']:
            # Return a copy: validators may mutate their inputs.
            return True, json.loads(json.dumps(self.data['responses'][key]))
        if self.data['pending']:
            raise RuntimeError('Предыдущий API-запрос имеет неизвестный результат. '
                               'Новый платный запрос заблокирован; требуется проверка.')
        return False, None

    def begin(self, key, budget):
        self.data.update(pending=key, calls=budget.calls, spent=budget.spent)
        # Must be durable BEFORE sending a paid request.
        self.save()

    def finish(self, key, result, budget):
        self.data['responses'][key] = result
        self.data.update(pending=None, calls=budget.calls, spent=budget.spent)
        self.save()

    def begin_delivery(self, bundle):
        key = fingerprint(bundle)
        delivery = self.data.get('delivery')
        if delivery:
            if delivery.get('key') == key and delivery.get('status') == 'sent':
                return False
            raise RuntimeError('Предыдущая отправка требует проверки; повторная публикация заблокирована.')
        self.data['delivery'] = {'key': key, 'status': 'pending', 'bundle': bundle}
        self.save()
        return True

    def finish_delivery(self, message_id):
        self.data['delivery'].update(status='sent', message_id=message_id)
        self.save()
