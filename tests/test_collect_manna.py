import datetime as dt
import importlib.util
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
from email.message import Message

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parents[1] / 'scripts/collect_manna.py')
assert spec is not None and spec.loader is not None
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CollectorTest(unittest.TestCase):
    def test_source_date_must_match(self):
        request = Mock(side_effect=[json.dumps([{'subject': '히 12:11-17', 'opened': '2026-11-16 00:00:00'}]),
            '@@'.join(['', 'ok', '', '', '', '', '', '<a class="viewLink" data-conname="이전 본문"><h7>2026-11-16</h7></a>'])])
        with self.assertRaisesRegex(ValueError, 'No verified'):
            c.select_subject('2026-11-17', request)

    def test_official_mobile_date_is_selected(self):
        request = Mock(side_effect=[json.dumps([{'subject': '이전 본문', 'opened': '2026-11-16 00:00:00'}]),
            '@@'.join(['', 'ok', '', '', '', '', '', '<a class="viewLink" data-conname="히 12:11-17"><h7>2026-11-17</h7></a>'])])
        self.assertEqual(c.select_subject('2026-11-17', request), '히 12:11-17')

    def test_parse_preserves_text_and_decodes_entities(self):
        html = '<div class="sentenceBox" data-bookname="히 12:11"><span class="sentence">  원문 &amp; <b>본문</b>  </span></div>'
        self.assertEqual(c.parse_verses(html), [{'bookname': '히 12:11', 'sentence': '원문 & 본문'}])

    def test_empty_and_duplicate_verses_rejected(self):
        for html in ['', '<div class="sentenceBox" data-bookname="히 12:11"><span class="sentence"></span></div>',
                     '<div class="sentenceBox" data-bookname="히 12:11"><span class="sentence">본문</span></div>' * 2]:
            with self.subTest(html=html), self.assertRaises(ValueError):
                c.parse_verses(html)

    def test_manifest_is_bound_to_bytes_and_date_not_commit_time(self):
        # Each test owns its directory. In agent runs TMPDIR is explicitly scratch.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verses = [{'bookname': '히 12:11', 'sentence': '본문'}]
            now = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
            self.assertTrue(c.write_backup(root, '2026-11-17', '히 12:11', verses, now))
            metadata = json.loads((root / 'manna_metadata.json').read_text())
            self.assertEqual(metadata['sha256'], c.hashlib.sha256((root / 'process_result.json').read_bytes()).hexdigest())
            self.assertEqual(metadata['dateKey'], '2026-11-17')
            self.assertFalse(c.write_backup(root, '2026-11-17', '히 12:11', verses, now))
            self.assertTrue(c.write_backup(root, '2026-11-18', '히 12:11', verses, now))
            self.assertEqual(json.loads((root / 'manna_metadata.json').read_text())['dateKey'], '2026-11-18')

    @patch.object(c.time, 'sleep')
    def test_transport_retries_are_bounded(self, sleep):
        client = c.JbchClient()
        client.opener.open = Mock(side_effect=urllib.error.URLError('sensitive upstream text'))
        with self.assertRaisesRegex(RuntimeError, 'attempts=3') as error:
            client.request(c.API)
        self.assertNotIn('sensitive', str(error.exception))
        self.assertEqual(client.opener.open.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(c.time, 'sleep')
    def test_auth_and_rate_limit_errors_are_not_retried(self, sleep):
        for status in [401, 403, 429, 500]:
            client = c.JbchClient()
            client.opener.open = Mock(side_effect=urllib.error.HTTPError(c.API, status, 'error', Message(), io.BytesIO(b'')))
            with self.assertRaisesRegex(RuntimeError, f'HTTP {status}'):
                client.request(c.API)
            self.assertEqual(client.opener.open.call_count, 1)
        sleep.assert_not_called()

    def test_failed_collection_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'process_result.json'
            path.write_text('existing payload')
            with self.assertRaises(ValueError):
                c.collect('2026-11-17', Mock(side_effect=[json.dumps([]), 'bad schedule']))
            self.assertEqual(path.read_text(), 'existing payload')


if __name__ == '__main__':
    unittest.main()
