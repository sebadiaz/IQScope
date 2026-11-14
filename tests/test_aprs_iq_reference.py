import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.aprs_iq_reference import ARCHIVE_BYTES, ARCHIVE_BUDGET, source_wave


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
