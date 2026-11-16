"""Compare a lab value with the reference range printed on the same report. Deterministic code, never a model.

A flag is only meaningful against the right range, and ranges depend on the analyser, species, age and breed. This
module therefore never supplies a range of its own: with no printed range the result is "not judged". It converts
units where the conversion is exact, and refuses to judge when a unit is unknown or the value is implausible.
"""

# analyte -> (canonical unit label, {normalised unit spelling: factor to canonical}, (plausible min, plausible max))
ANALYTES = {
    'pcv': ('%', {'%': 1.0, 'percent': 1.0, 'l/l': 100.0}, (0, 100)),
    'hemoglobin': ('g/dL', {'g/dl': 1.0, 'gm/dl': 1.0, 'g/l': 0.1}, (0, 40)),
    'rbc': ('x10^12/L', {'x1012/l': 1.0, '1012/l': 1.0, 'x10e12/l': 1.0, '10e12/l': 1.0, 't/l': 1.0,
                         'm/ul': 1.0, 'x106/ul': 1.0, '106/ul': 1.0, 'mil/ul': 1.0}, (0, 20)),
    'wbc': ('x10^9/L', {'x109/l': 1.0, '109/l': 1.0, 'x10e9/l': 1.0, '10e9/l': 1.0, 'g/l': 1.0, 'k/ul': 1.0,
                        'x103/ul': 1.0, '103/ul': 1.0, '/ul': 0.001, 'cells/ul': 0.001, '/mm3': 0.001}, (0, 1000)),
    'platelets': ('x10^9/L', {'x109/l': 1.0, '109/l': 1.0, 'x10e9/l': 1.0, '10e9/l': 1.0, 'g/l': 1.0, 'k/ul': 1.0,
                              'x103/ul': 1.0, '103/ul': 1.0, '/ul': 0.001, 'cells/ul': 0.001, '/mm3': 0.001}, (0, 5000)),
    'mcv': ('fL', {'fl': 1.0}, (20, 200)),
    'mchc': ('g/dL', {'g/dl': 1.0, 'gm/dl': 1.0, 'g/l': 0.1, '%': 1.0}, (10, 60)),
}
SUPPORTED = tuple(ANALYTES)


def normalise_unit(unit):
    """Lower-case, strip spaces and exponent marks so 'x10^9/L', '10e9 /l' and 'X10⁹/L' compare equal."""
    if unit is None:
        return ''
    text = str(unit).strip().lower()
    for old, new in (('µ', 'u'), ('μ', 'u'), ('×', 'x'), ('^', ''), ('*', ''), (' ', ''), ('⁹', '9'), ('¹²', '12'), ('³', '3'), ('⁶', '6')):
        text = text.replace(old, new)
    return text


def convert(analyte, value, unit):
    """Return the value in the analyte's canonical unit, or None when the unit is not an exact known spelling."""
    if analyte not in ANALYTES or value is None:
        return None
    factor = ANALYTES[analyte][1].get(normalise_unit(unit))
    return None if factor is None else value * factor


def judge(analyte, value, unit, low=None, high=None, range_unit=None, qualifier=None, sample_note=None):
    """Flag a value 'low', 'normal', 'high' or 'not_judged' against the printed range. Returns a dict with the reason."""
    result = dict(flag='not_judged', reason='', canonical_unit=None, value=None, low=None, high=None, caution=sample_note or None)
    if analyte not in ANALYTES:
        result['reason'] = 'This test is not one of the supported blood count values.'
        return result
    canonical_unit, _, (plausible_low, plausible_high) = ANALYTES[analyte]
    result['canonical_unit'] = canonical_unit
    if value is None:
        result['reason'] = 'No numeric value was found.'
        return result
    if qualifier:
        result['reason'] = f'The value is reported with a qualifier ({qualifier}), so it is not compared.'
        return result
    converted = convert(analyte, value, unit)
    if converted is None:
        result['reason'] = f'The unit "{unit or "not given"}" is not recognised for this test.'
        return result
    if not plausible_low <= converted <= plausible_high:
        result['reason'] = 'The value is implausible for this unit. Check the unit and the source text.'
        return result
    if low is None and high is None:
        result['reason'] = 'No reference range was printed in the record.'
        return result
    range_unit = range_unit or unit
    bounds = [None if bound is None else convert(analyte, bound, range_unit) for bound in (low, high)]
    if any(b is None for b, original in zip(bounds, (low, high)) if original is not None):
        result['reason'] = f'The range unit "{range_unit or "not given"}" is not recognised for this test.'
        return result
    low_c, high_c = bounds
    if low_c is not None and high_c is not None and low_c > high_c:
        result['reason'] = 'The printed range is invalid (low is above high).'
        return result
    result.update(value=converted, low=low_c, high=high_c)
    if low_c is not None and converted < low_c - 1e-9:
        result['flag'] = 'low'
    elif high_c is not None and converted > high_c + 1e-9:
        result['flag'] = 'high'
    else:
        result['flag'] = 'normal'
    result['reason'] = 'Compared with the range printed in the record.'
    return result
