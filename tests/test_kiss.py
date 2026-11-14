"""KISS wire-format vectors and received-frame preservation across file export."""
import copy
from pathlib import Path
import tempfile
import unittest

from iqscope_ax25 import encode_kiss_frame
from iqscope_afsk_fm import write_afsk_fm_artifact
from test_ax25 import frame, with_fcs


def read_kiss(data):
    """Independent receiver for the data-only subset exercised by the exporter."""
    packets = []
    for chunk in data.split(bytes([192])):
        if not chunk:
            continue
        decoded = bytearray()
        escaped = False
        for value in chunk:
            if escaped:
                decoded.append({220:192, 221:219}[value])
                escaped = False
            elif value==219:
                escaped = True
            else:
                decoded.append(value)
        assert not escaped
        packets.append((decoded[0]>>4, decoded[0]&15, bytes(decoded[1:])))
    return packets


class KissTests(unittest.TestCase):
    def test_literal_transparency_vector_and_fcs_removal(self):
        packet = frame(payload=bytes.fromhex('c0dbdcdd'))
        self.assertEqual(encode_kiss_frame(packet), bytes.fromhex(
            'c00082a0a4a64040609c60868298986303f0dbdcdbdddcddc0'))

    def test_command_octet_is_escaped_as_well_as_data(self):
        packet = frame(payload=b'hello')
        for port in range(16):
            encoded = encode_kiss_frame(packet, port)
            self.assertEqual(read_kiss(encoded), [(port, 0, packet[:-2])])
            if port==12:
                self.assertEqual(encoded[:3], bytes.fromhex('c0dbdc'))

    def test_invalid_fcs_and_unsupported_inputs_are_rejected(self):
        for packet in (frame(bad=True), b'', with_fcs(b'A'*14), with_fcs(b'A'*330), frame().hex()):
            with self.assertRaises(ValueError):
                encode_kiss_frame(packet)
        for port in (-1, 16, True, 1.5, '0', None):
            with self.assertRaises(ValueError):
                encode_kiss_frame(frame(), port)

    def test_export_retains_ambiguous_link_frames_and_separated_repetitions(self):
        # Three distinct on-air frames from the pinned IQ development reference.
        raw = [bytes.fromhex(h) for h in (
            '9664b2b28840f49c64a4a2404072ae6496a0a240e544f03b204b325959442d3130204445204e3252512d392028464e33304651292051544320302e2e2e0dc7ae',
            '9c64a4a2404072ae6496a0a240e1b1373c',
            '9664b2b28840f49c64a4a2404072ae6496a0a240e546f046460de132')]
        from iqscope_ax25_link import parse_link
        trial = {'frames':[dict(hex=p.hex(), fields=parse_link(p[:-2]), time_seconds=i)
                           for i,p in enumerate(raw+[raw[0]])]}
        original = copy.deepcopy(trial['frames'])
        with tempfile.TemporaryDirectory() as directory:
            write_afsk_fm_artifact(trial, directory)
            stream = (Path(directory)/trial['kiss_artifact']).read_bytes()
            self.assertEqual(read_kiss(stream), [(0, 0, p[:-2]) for p in raw+[raw[0]]])
            for before,after in zip(original,trial['frames']):
                self.assertEqual(before['hex'],after['hex'])
                self.assertEqual(before['fields'],after['fields'])
                self.assertIsNone(after['fields']['pid'])
                self.assertEqual(after['fields']['payload_hex'],'')
                self.assertNotIn('payload_artifact',after)
            self.assertEqual(trial['kiss_export']['frame_count'],4)
            self.assertFalse(trial['kiss_export']['fcs_included'])
            self.assertFalse(trial['kiss_export']['timestamps_included'])

    def test_failed_export_does_not_write_a_partial_stream_or_frame_files(self):
        trial = {'frames':[dict(hex=p.hex(),fields={'frame_type':'UI','payload_hex':''})
                           for p in (frame(),frame(bad=True))]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_afsk_fm_artifact(trial, directory)
            self.assertEqual(list(Path(directory).iterdir()),[])
            self.assertNotIn('kiss_artifact',trial)

    def test_no_kiss_artifact_without_validated_frames(self):
        trial = {'frames':[]}
        with tempfile.TemporaryDirectory() as directory:
            write_afsk_fm_artifact(trial, directory)
            self.assertNotIn('kiss_artifact',trial)
            self.assertEqual(list(Path(directory).iterdir()),[])
