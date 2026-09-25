"""Astronomical measurements, separate from explicitly symbolic solar-sign houses."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from itertools import combinations
from pathlib import Path
import hashlib
import math

SIGNS = 'Овен Телец Близнецы Рак Лев Дева Весы Скорпион Стрелец Козерог Водолей Рыбы'.split()
BODIES = {'Солнце': 'sun', 'Луна': 'moon', 'Меркурий': 'mercury', 'Венера': 'venus',
          'Марс': 'mars', 'Юпитер': 'jupiter barycenter', 'Сатурн': 'saturn barycenter',
          'Уран': 'uranus barycenter', 'Нептун': 'neptune barycenter', 'Плутон': 'pluto barycenter'}
RULERS = ['Марс', 'Венера', 'Меркурий', 'Луна', 'Солнце', 'Меркурий',
          'Венера', 'Плутон', 'Юпитер', 'Сатурн', 'Уран', 'Нептун']
THEMES = ['личная инициатива', 'личные деньги и покупки', 'общение и обучение',
          'дом и семья', 'творчество и симпатия', 'обычные обязанности и распорядок',
          'партнёрство и договорённости', 'общие расходы и обязательства',
          'расширение кругозора', 'работа и ответственность', 'друзья и совместные планы',
          'отдых и уединение']

def signed_angle(value):
    return (value + 180) % 360 - 180

def house(longitude, sign_index):
    return (int((longitude % 360) // 30) - sign_index) % 12 + 1

def aspects(positions, orb=3.0):
    result = []
    for a, b in combinations(positions, 2):
        separation = abs(signed_angle(positions[a] - positions[b]))
        for angle, name in [(0, 'соединение'), (60, 'секстиль'), (90, 'квадрат'),
                            (120, 'тригон'), (180, 'оппозиция')]:
            delta = abs(separation - angle)
            if delta <= orb:
                result.append({'bodies': [a, b], 'type': name, 'angle': angle,
                               'orb': round(delta, 3)})
    return sorted(result, key=lambda x: x['orb'])

def calculate(day, directory='astro-data'):
    from skyfield.api import Loader
    from skyfield.framelib import ecliptic_frame
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(directory))
    ts = loader.timescale(builtin=True)
    eph = loader('de421.bsp')
    start = datetime.combine(day, time(), ZoneInfo('Europe/Moscow'))
    def positions(hour):
        t = ts.from_datetime(start + timedelta(hours=hour))
        observer = eph['earth'].at(t)
        return {name: float(observer.observe(eph[target]).apparent().frame_latlon(ecliptic_frame)[1].degrees) % 360
                for name, target in BODIES.items()}
    try:
        samples = {str(h): positions(h) for h in (0, 11, 12, 13, 24)}
    finally:
        eph.close()
    noon = samples['12']
    phase = (noon['Луна'] - noon['Солнце']) % 360
    measured = {}
    for body, longitude in noon.items():
        speed = signed_angle(samples['13'][body] - samples['11'][body]) * 12
        measured[body] = {'longitude': round(longitude, 5), 'sign': SIGNS[int(longitude // 30)],
                          'speed_deg_per_day': round(speed, 5), 'retrograde': speed < 0}
    contexts = {}
    for i, sign in enumerate(SIGNS):
        contexts[sign] = {'ruler': RULERS[i], 'solar_whole_sign_houses': {
            body: {'house': house(noon[body], i), 'symbolic_theme': THEMES[house(noon[body], i)-1]}
            for body in ('Луна', 'Меркурий', 'Венера', 'Марс', RULERS[i])}}
    return {'date': str(day), 'source': 'JPL DE421 / Skyfield 1.54',
            'ephemeris_sha256': hashlib.sha256((directory / 'de421.bsp').read_bytes()).hexdigest(),
            'measurement': 'Geocentric apparent tropical longitude; true ecliptic/equinox of date; 12:00 Europe/Moscow',
            'positions': measured, 'aspects_at_noon': aspects(noon),
            'moon': {'elongation_deg': round(phase, 3), 'waxing': phase < 180,
                     'illumination_approx': round((1-math.cos(math.radians(phase)))/2, 4),
                     'longitude_at_local_day_start': round(samples['0']['Луна'], 4),
                     'longitude_at_next_day_start': round(samples['24']['Луна'], 4)},
            'symbolic_method': 'Solar whole-sign houses, sign itself treated as house 1. Not natal houses or individual transits. Astrology has no scientifically established predictive accuracy.',
            'sign_context': contexts}
