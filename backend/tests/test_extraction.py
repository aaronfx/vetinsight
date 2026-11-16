import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from tests import test_api
from app import extraction

RECORD_LINES = [
    'SYNTHETIC RECORD FOR TESTING',
    'Species: Dog   Breed: Mixed breed   Sex: Female   Age: 6 years',
    'Presenting complaint: intermittent vulvar discharge for 5 days',
    'PCV 22 % (37 - 55)',
    'WBC 12.0 x10^9/L',
]


def pdf_with_text(lines):
    def esc(text):
        return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = '\n'.join(['BT', '50 790 Td', '14 TL', '/F1 10 Tf'] + [f'({esc(line)}) \'' for line in lines] + ['ET']).encode('latin-1')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


def field(value=None, quote=None):
    return {'value': value, 'quote': quote}


def raw_extraction(**overrides):
    raw = {name: field() for name in extraction.SIMPLE_FIELDS}
    raw.update(species=field('Dog', 'Species: Dog'), age=field('6 years', 'Age: 6 years'),
               presenting_complaint=field('intermittent vulvar discharge for 5 days',
                                          'Presenting complaint: intermittent vulvar discharge for 5 days'))
    raw['medications'] = []
    raw['lab_results'] = [{'analyte': 'pcv', 'name_as_written': 'PCV', 'value': 22, 'qualifier': None, 'unit': '%',
                           'range_low': 37, 'range_high': 55, 'range_unit': None, 'sample_note': None, 'quote': 'PCV 22 % (37 - 55)'}]
    raw.update(overrides)
    return raw


TEXT = '\n'.join(RECORD_LINES)


class BuildResultTests(unittest.TestCase):
    def test_flags_a_verified_lab_value_against_the_printed_range(self):
        result = extraction.build_result(raw_extraction(), TEXT)
        lab = result['lab_results'][0]
        self.assertTrue(lab['found_in_record'])
        self.assertEqual(lab['flag'], 'low')
        self.assertEqual(result['summary']['labs_outside_range'], 1)
        self.assertTrue(result['fields']['species']['found_in_record'])
        self.assertIsNone(result['fields']['breed']['value'])

    def test_a_quote_that_is_not_in_the_record_is_marked_and_never_judged(self):
        raw = raw_extraction()
        raw['lab_results'][0]['quote'] = 'PCV 22 % (35 - 50)'
        raw['species'] = field('Cat', 'Species: Cat')
        result = extraction.build_result(raw, TEXT)
        self.assertFalse(result['lab_results'][0]['found_in_record'])
        self.assertEqual(result['lab_results'][0]['flag'], 'not_judged')
        self.assertFalse(result['fields']['species']['found_in_record'])
        self.assertEqual(result['summary']['not_found_in_record'], 2)

    def test_a_value_not_present_in_its_quote_is_not_trusted(self):
        raw = raw_extraction()
        raw['lab_results'][0]['value'] = 25  # quote says 22
        self.assertFalse(extraction.build_result(raw, TEXT)['lab_results'][0]['found_in_record'])

    def test_a_range_missing_from_the_quote_is_ignored(self):
        raw = raw_extraction()
        raw['lab_results'][0].update(range_low=30, range_high=60)  # not what the quote prints
        lab = extraction.build_result(raw, TEXT)['lab_results'][0]
        self.assertEqual(lab['flag'], 'not_judged')
        self.assertIn('could not be confirmed', lab['reason'])

    def test_no_printed_range_is_not_judged(self):
        raw = raw_extraction()
        raw['lab_results'] = [{'analyte': 'wbc', 'name_as_written': 'WBC', 'value': 12.0, 'qualifier': None, 'unit': 'x10^9/L',
                               'range_low': None, 'range_high': None, 'range_unit': None, 'sample_note': None, 'quote': 'WBC 12.0 x10^9/L'}]
        lab = extraction.build_result(raw, TEXT)['lab_results'][0]
        self.assertTrue(lab['found_in_record'])
        self.assertEqual(lab['flag'], 'not_judged')
        self.assertIn('No reference range', lab['reason'])

    def test_whitespace_and_case_differences_in_a_quote_are_tolerated(self):
        raw = raw_extraction(species=field('Dog', 'species:  dog'))
        self.assertTrue(extraction.build_result(raw, TEXT)['fields']['species']['found_in_record'])

    def test_record_text_rejects_scans_and_overlong_records(self):
        with self.assertRaises(extraction.UserError):
            extraction.record_text([{'page_number': 1, 'text': '', 'status': 'ocr_required'}])
        with self.assertRaises(extraction.UserError):
            extraction.record_text([{'page_number': 1, 'text': 'x' * (extraction.MAX_TEXT_CHARACTERS + 1), 'status': 'extracted'}])
        self.assertIn('--- page 1 ---', extraction.record_text([{'page_number': 1, 'text': 'hello', 'status': 'extracted'}]))


class FakeClient:
    def __init__(self, stop_reason='end_turn', text='{}'):
        block = SimpleNamespace(type='text', text=text)
        self.response = SimpleNamespace(stop_reason=stop_reason, content=[block], model='claude-haiku-5-5',
                                        usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class CallModelTests(unittest.TestCase):
    def call(self, client):
        with patch('anthropic.Anthropic', return_value=client):
            return extraction.call_model('record text')

    def test_sends_the_configured_model_a_json_schema_and_no_unsupported_settings(self):
        client = FakeClient(text='{"a": 1}')
        with patch.dict(os.environ, {'VETINSIGHT_EXTRACTION_MODEL': 'claude-sonnet-5-5'}):
            parsed, usage = self.call(client)
        sent = client.calls[0]
        self.assertEqual(sent['model'], 'claude-sonnet-5-5')
        self.assertEqual(sent['output_config']['format']['type'], 'json_schema')
        self.assertNotIn('temperature', sent)
        self.assertNotIn('thinking', sent)
        self.assertEqual(parsed, {'a': 1})
        self.assertEqual(usage['input_tokens'], 10)

    def test_default_model_is_haiku(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VETINSIGHT_EXTRACTION_MODEL', None)
            self.assertEqual(extraction.model_name(), 'claude-haiku-5-5')

    def test_refusal_truncation_and_bad_json_become_safe_messages(self):
        for client, expected in ((FakeClient('refusal'), 'declined'), (FakeClient('max_tokens'), 'more output'),
                                 (FakeClient(text='not json'), 'unreadable')):
            with self.assertRaises(extraction.UserError) as raised:
                self.call(client)
            self.assertIn(expected, str(raised.exception))


class ExtractionApiTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def upload(self, content=None, name='record.pdf', content_type='application/pdf'):
        case = self.create()
        data = content if content is not None else pdf_with_text(RECORD_LINES)
        upload = self.client.post(f'/cases/{case}/uploads', files={'file': (name, data, content_type)}).json()
        return case, f'/cases/{case}/uploads/{upload["id"]}'

    def wait(self, path):
        for _ in range(200):
            run = self.client.get(path + '/extraction').json()[0]
            if run['status'] not in ('queued', 'running'):
                return run
            time.sleep(.02)
        self.fail('extraction did not finish')

    def payload(self, **overrides):
        return {'request_id': str(uuid4()), 'acknowledge_experimental': True, **overrides}

    def test_status_reports_missing_key_then_available(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            body = self.client.get('/extraction/status').json()
            self.assertFalse(body['available'])
            self.assertIn('No Anthropic API key', body['reason'])
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            self.assertTrue(self.client.get('/extraction/status').json()['available'])

    def test_run_completes_flags_labs_and_leaves_the_case_unchanged(self):
        case, path = self.upload()
        before = self.client.get(f'/cases/{case}').json()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                patch.object(extraction, 'call_model', return_value=(raw_extraction(), dict(model='claude-haiku-5-5', input_tokens=9, output_tokens=4))):
            response = self.client.post(path + '/extraction', json=self.payload())
            self.assertEqual(response.status_code, 202, response.text)
            run = self.wait(path)
        self.assertEqual(run['status'], 'completed', run)
        self.assertEqual(run['result']['lab_results'][0]['flag'], 'low')
        self.assertEqual(run['result']['summary']['labs_outside_range'], 1)
        self.assertEqual(len(run['text_sha256']), 64)
        self.assertEqual(self.client.get(f'/cases/{case}').json(), before)

    def test_requires_acknowledgement_a_key_and_a_pdf(self):
        case, path = self.upload()
        self.assertEqual(self.client.post(path + '/extraction', json=self.payload(acknowledge_experimental=False)).status_code, 422)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            self.assertEqual(self.client.post(path + '/extraction', json=self.payload()).status_code, 503)
        _, image_path = self.upload(content=b'\x89PNG\r\n\x1a\n' + b'0' * 40, name='x.png', content_type='image/png')
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            self.assertEqual(self.client.post(image_path + '/extraction', json=self.payload()).status_code, 415)

    def test_repeat_request_id_returns_the_same_run(self):
        _, path = self.upload()
        body = self.payload()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                patch.object(extraction, 'call_model', return_value=(raw_extraction(), dict(model='m', input_tokens=1, output_tokens=1))):
            first = self.client.post(path + '/extraction', json=body).json()
            self.wait(path)
            again = self.client.post(path + '/extraction', json=body).json()
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(len(self.client.get(path + '/extraction').json()), 1)

    def test_a_model_failure_is_reported_without_internal_detail(self):
        _, path = self.upload()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                patch.object(extraction, 'call_model', side_effect=RuntimeError('secret internal detail')):
            self.client.post(path + '/extraction', json=self.payload())
            run = self.wait(path)
        self.assertEqual(run['status'], 'failed')
        self.assertNotIn('secret', run['error'])

    def test_user_errors_are_shown_and_restart_marks_interrupted_runs(self):
        _, path = self.upload()
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}), \
                patch.object(extraction, 'call_model', side_effect=extraction.UserError('The model service is busy. Try again in a minute.')):
            self.client.post(path + '/extraction', json=self.payload())
            self.assertIn('busy', self.wait(path)['error'])
        with self.main.database() as db:
            upload = db.execute('SELECT id FROM uploads').fetchone()['id']
            db.execute('INSERT INTO extraction_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (str(uuid4()), upload, 1, 'running', '{}', '', 'm', '', extraction.stamp(), extraction.stamp()))
        with self.main.database() as db:
            extraction.initialize(db)
        self.assertIn('restart', self.client.get(path + '/extraction').json()[0]['error'])


if __name__ == '__main__':
    unittest.main()
