import unittest
from astro_context import house, aspects, signed_angle, SIGNS
from astro_preview import validate_basis

class AstroTests(unittest.TestCase):
    def test_wraparound(self):
        self.assertEqual(signed_angle(1-359), 2)
        self.assertEqual(signed_angle(359-1), -2)
        self.assertEqual(house(359, 0), 12)
        self.assertEqual(house(0, 11), 2)
        self.assertEqual(house(30, 1), 1)

    def test_aspect_orb_and_wraparound(self):
        self.assertEqual(aspects({'a': 359, 'b': 1})[0]['type'], 'соединение')
        self.assertEqual(aspects({'a': 0, 'b': 93})[0]['orb'], 3)
        self.assertEqual(aspects({'a': 0, 'b': 94}), [])
        self.assertEqual(aspects({'a': 0, 'b': 180})[0]['type'], 'оппозиция')

    def test_basis_must_match_calculated_house(self):
        sky = {'sign_context': {s: {'solar_whole_sign_houses': {'Луна': {'house': 2}}} for s in SIGNS}}
        result = {'basis': {s: {'body': 'Луна', 'house': 2, 'interpretation': 'Образ денег'} for s in SIGNS}}
        validate_basis(result, sky)
        result['basis']['Овен']['house'] = 9
        with self.assertRaises(ValueError):
            validate_basis(result, sky)
