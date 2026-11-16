import unittest

from app import labs


class LabJudgementTests(unittest.TestCase):
    def test_low_normal_and_high_against_the_printed_range(self):
        self.assertEqual(labs.judge('pcv', 22, '%', 37, 55)['flag'], 'low')
        self.assertEqual(labs.judge('pcv', 45, '%', 37, 55)['flag'], 'normal')
        self.assertEqual(labs.judge('pcv', 60, '%', 37, 55)['flag'], 'high')

    def test_boundary_values_are_normal(self):
        self.assertEqual(labs.judge('pcv', 37, '%', 37, 55)['flag'], 'normal')
        self.assertEqual(labs.judge('pcv', 55, '%', 37, 55)['flag'], 'normal')

    def test_converts_units_in_value_and_range(self):
        self.assertEqual(labs.judge('pcv', 0.22, 'L/L', 37, 55, range_unit='%')['flag'], 'low')
        self.assertEqual(labs.judge('hemoglobin', 80, 'g/L', 12, 18, range_unit='g/dL')['flag'], 'low')
        self.assertEqual(labs.judge('wbc', 15000, '/uL', 6, 17, range_unit='x10^9/L')['flag'], 'normal')
        self.assertEqual(labs.judge('platelets', 90, 'K/µL', 200, 500)['flag'], 'low')
        self.assertEqual(labs.judge('rbc', 6.0, 'x10^12/L', 5.5, 8.5, range_unit='M/µL')['flag'], 'normal')

    def test_one_sided_range(self):
        self.assertEqual(labs.judge('wbc', 25, 'x10^9/L', None, 17)['flag'], 'high')
        self.assertEqual(labs.judge('wbc', 5, 'x10^9/L', None, 17)['flag'], 'normal')

    def test_never_judges_without_a_printed_range(self):
        result = labs.judge('pcv', 22, '%', None, None)
        self.assertEqual(result['flag'], 'not_judged')
        self.assertIn('No reference range', result['reason'])

    def test_refuses_unknown_units_unknown_tests_qualifiers_and_implausible_values(self):
        self.assertEqual(labs.judge('pcv', 22, 'mmol', 37, 55)['flag'], 'not_judged')
        self.assertEqual(labs.judge('pcv', 22, '%', 37, 55, range_unit='mmol')['flag'], 'not_judged')
        self.assertEqual(labs.judge('creatinine', 90, 'umol/L', 40, 130)['flag'], 'not_judged')
        self.assertEqual(labs.judge('pcv', 22, '%', 37, 55, qualifier='<')['flag'], 'not_judged')
        self.assertEqual(labs.judge('pcv', 220, '%', 37, 55)['flag'], 'not_judged')
        self.assertEqual(labs.judge('pcv', None, '%', 37, 55)['flag'], 'not_judged')
        self.assertEqual(labs.judge('pcv', 22, '%', 55, 37)['flag'], 'not_judged')

    def test_sample_note_is_carried_as_a_caution(self):
        result = labs.judge('pcv', 22, '%', 37, 55, sample_note='haemolysed sample')
        self.assertEqual(result['flag'], 'low')
        self.assertEqual(result['caution'], 'haemolysed sample')

    def test_unit_spellings_are_normalised(self):
        self.assertEqual(labs.normalise_unit(' X10^9 /L '), 'x109/l')
        self.assertEqual(labs.normalise_unit('K/µL'), 'k/ul')
        self.assertEqual(labs.normalise_unit(None), '')


if __name__ == '__main__':
    unittest.main()
