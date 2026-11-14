"""Published independent transmitter profile; actual sound-card WAV tested in CI."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from iqscope_aprs import parse_aprs_position
from scripts.aprs_pico_reference import EXPECTED_PAYLOAD, SOURCE_BYTES, verified_source


class AprsPicoReferenceTests(unittest.TestCase):
    def test_published_profile_has_quantized_coordinates_and_rounded_feet(self):
        value = parse_aprs_position(EXPECTED_PAYLOAD)
        self.assertEqual(value['status'], 'decoded_position')
        self.assertEqual(value['format'], 'compressed')
        self.assertAlmostEqual(value['latitude_deg'], 48.755881719809096, places=12)
        self.assertAlmostEqual(value['longitude_deg'], 9.190105164782665, places=12)
        self.assertEqual(value['altitude_ft'], 1585)
        self.assertAlmostEqual(value['altitude_m'], 483.108, places=12)
        self.assertNotEqual(value['altitude_m'], 483)  # Encoded feet were rounded upstream.
        self.assertEqual(value['compressed_extension_hex'], '202020')
        for key in ('course_deg', 'speed_knots', 'telemetry'):
            self.assertNotIn(key, value)

    def test_bounded_invalid_download_never_populates_source_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            for length in (SOURCE_BYTES, SOURCE_BYTES+1):
                stream = io.BytesIO(bytes(length))
                with patch('scripts.aprs_pico_reference.urllib.request.urlopen', return_value=stream), \
                        patch.object(stream, 'read', wraps=stream.read) as read:
                    with self.assertRaisesRegex(ValueError, 'size/Git blob'):
                        verified_source(Path(directory))
                    read.assert_called_once_with(SOURCE_BYTES+1)
                    self.assertTrue(stream.closed)
                self.assertFalse((Path(directory)/'aprs_pico_beacon_demo.wav').exists())
