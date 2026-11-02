from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import unittest

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tests import test_api


def pdf_bytes(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=400)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 20 300 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


class DocumentTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    create = test_api.ApiTests.create

    def attach(self, content, filename='record.pdf'):
        case_id = self.create()
        response = self.client.post(f'/cases/{case_id}/uploads', files={'file': (filename, content)})
        self.assertEqual(response.status_code, 201)
        return case_id, response.json()

    def test_inline_download_and_page_boundaries(self):
        content = pdf_bytes(['Page one fictional record', 'Page two document text'])
        case_id, info = self.attach(content)
        before = self.client.get(f'/cases/{case_id}').json()
        for key, disposition in [('preview_url', 'inline'), ('download_url', 'attachment')]:
            response = self.client.get(info[key])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, content)
            self.assertEqual(response.headers['content-type'], 'application/pdf')
            self.assertTrue(response.headers['content-disposition'].startswith(disposition))
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertIn('sandbox', response.headers['content-security-policy'])
        response = self.client.get(info['text_url'])
        self.assertEqual(response.status_code, 200, response.text)
        text = response.json()
        self.assertEqual(text['status'], 'extracted')
        self.assertEqual(text['page_count'], 2)
        self.assertEqual([p['page_number'] for p in text['pages']], [1, 2])
        self.assertIn('Page one', text['pages'][0]['text'])
        self.assertIn('Page two', text['pages'][1]['text'])
        self.assertEqual(self.client.get(f'/cases/{case_id}').json(), before)
        # Inline supports byte ranges used by document clients.
        partial = self.client.get(info['preview_url'], headers={'Range': 'bytes=0-4'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b'%PDF-')

    def test_no_embedded_text_and_mixed_pages(self):
        for texts, status in [(['', ''], 'ocr_required'), (['Text page', ''], 'partial')]:
            _, info = self.attach(pdf_bytes(texts))
            result = self.client.get(info['text_url']).json()
            self.assertEqual(result['status'], status)
            self.assertEqual(result['pages'][-1]['status'], 'ocr_required')
            self.assertEqual(result['pages'][-1]['text'], '')

    def test_missing_unsupported_and_damaged(self):
        case_id, info = self.attach(pdf_bytes(['test']))
        other_id = self.create()
        for suffix in ['/preview', '/text']:
            self.assertEqual(self.client.get(f'/cases/{other_id}/uploads/{info["id"]}{suffix}').status_code, 404)
            self.assertEqual(self.client.get(f'/cases/{case_id}/uploads/999{suffix}').status_code, 404)
        with self.main.database() as db:
            row = db.execute('SELECT storage_name FROM uploads WHERE id=?', (info['id'],)).fetchone()
            db.execute("UPDATE uploads SET content_type='text/html' WHERE id=?", (info['id'],))
        self.assertEqual(self.client.get(info['preview_url']).status_code, 415)
        (Path(self.temp.name) / 'uploads' / row['storage_name']).unlink()
        for key in ['preview_url', 'download_url', 'text_url']:
            self.assertEqual(self.client.get(info[key]).status_code, 404)
        _, damaged = self.attach(b'%PDF-1.4\nnot a valid document')
        with patch('app.main.logging.exception'):
            self.assertEqual(self.client.get(damaged['text_url']).status_code, 422)

    def test_image_delivery_and_encrypted_pdf(self):
        for filename, data, mime in [('scan.png', b'\x89PNG\r\n\x1a\nfixture', 'image/png'),
                                     ('scan.jpg', b'\xff\xd8\xfffixture', 'image/jpeg')]:
            _, info = self.attach(data, filename)
            response = self.client.get(info['preview_url'])
            self.assertEqual(response.headers['content-type'], mime)
            self.assertTrue(response.headers['content-disposition'].startswith('inline'))
            self.assertEqual(self.client.get(info['text_url']).status_code, 415)
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.encrypt('secret')
        buffer = BytesIO()
        writer.write(buffer)
        _, info = self.attach(buffer.getvalue())
        self.assertEqual(self.client.get(info['text_url']).status_code, 422)
