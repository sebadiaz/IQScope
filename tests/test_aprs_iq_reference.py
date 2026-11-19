import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from scripts.aprs_iq_reference import ARCHIVE_BYTES, ARCHIVE_BUDGET, SOURCE_URL, source_wave


class AprsIqReferenceTests(unittest.TestCase):
    def test_wrong_archive_is_bounded_and_rejected_before_native_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            stream=io.BytesIO(bytes(ARCHIVE_BYTES))
            with patch('scripts.aprs_iq_reference.urllib.request.urlopen',return_value=stream), \
                    patch.object(stream,'read',wraps=stream.read) as read, \
                    patch('scripts.aprs_iq_reference.subprocess.run') as execute:
                with self.assertRaisesRegex(ValueError,'size/SHA-256'):
                    source_wave(Path(directory))
                read.assert_called_once_with(ARCHIVE_BUDGET+1)
                execute.assert_not_called()
            self.assertFalse((Path(directory)/'recording.wav').exists())

    def test_timeout_retry_still_rejects_wrong_bytes_before_writing_or_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            stream=io.BytesIO(bytes(ARCHIVE_BYTES))
            with patch('scripts.aprs_iq_reference.urllib.request.urlopen',side_effect=[TimeoutError('temporary'),stream]) as fetch, \
                    patch.object(stream,'read',wraps=stream.read) as read, \
                    patch('scripts.aprs_iq_reference.subprocess.run') as execute:
                with self.assertRaisesRegex(ValueError,'size/SHA-256'):source_wave(Path(directory))
                self.assertEqual(fetch.call_count,2)
                self.assertTrue(all(c.kwargs['timeout']==20 for c in fetch.call_args_list))
                read.assert_called_once_with(ARCHIVE_BUDGET+1);execute.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_transport_failures_stop_after_three_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.aprs_iq_reference.urllib.request.urlopen',side_effect=urllib.error.URLError('temporary')) as fetch:
                with self.assertRaises(urllib.error.URLError):source_wave(Path(directory))
                self.assertEqual(fetch.call_count,3)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_server_errors_retry_but_client_errors_and_hash_mismatches_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            error=urllib.error.HTTPError(SOURCE_URL,503,'temporary',None,None)
            with patch('scripts.aprs_iq_reference.urllib.request.urlopen',side_effect=[error,io.BytesIO(b'wrong')]) as fetch:
                with self.assertRaisesRegex(ValueError,'size/SHA-256'):source_wave(Path(directory))
                self.assertEqual(fetch.call_count,2)
            for status in (403,404,429):
                with self.subTest(status=status),patch('scripts.aprs_iq_reference.urllib.request.urlopen',
                        side_effect=urllib.error.HTTPError(SOURCE_URL,status,'not retryable',None,None)) as fetch:
                    with self.assertRaises(urllib.error.HTTPError):source_wave(Path(directory))
                    fetch.assert_called_once()
            self.assertEqual(list(Path(directory).iterdir()),[])
