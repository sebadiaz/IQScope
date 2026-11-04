import json
from pathlib import Path
import tempfile
import unittest
from iqscope_funcube import interpret_funcube
from iqscope_ao40 import write_ao40_artifacts


def fixture(valid=True):
    packet=bytearray(256);packet[0]=0x89
    for i,value in enumerate((101,202,303,404,8123,205,7,8)):
        packet[1+2*i:3+2*i]=value.to_bytes(2,'big')
    packet[17:25]=bytes((128,129,130,131,132,133,134,135))
    packet[25:50]=bytes(range(25))
    packet[50:53]=(0x123456).to_bytes(3,'big')
    packet[54]=4 if valid else 0
    packet[55]=0x18
    packet[56:]=bytes(range(200))
    return bytes(packet)


class FuncubeTests(unittest.TestCase):
    def test_msb_offsets_values_flags_and_raw_preservation(self):
        raw=fixture();result=interpret_funcube(raw)
        self.assertEqual(result['status'],'candidate_interpretation')
        self.assertFalse(result['identity_confirmed'])
        fields={m['id']:m for m in result['measurements']}
        self.assertEqual(fields['battery_voltage']['value'],8123)
        self.assertEqual(fields['battery_voltage']['unit'],'mV')
        self.assertEqual(fields['battery_voltage']['bit_offset'],72)
        self.assertEqual(fields['system_current']['value'],205)
        self.assertEqual(fields['system_current']['unit'],'mA')
        self.assertEqual(result['sequence_number'],0x123456)
        self.assertTrue(result['source_validity']['eps'])
        self.assertFalse(result['source_validity']['rf'])
        self.assertTrue(result['modes']['eclipse'])
        self.assertTrue(result['modes']['safe_mode'])
        self.assertFalse(result['modes']['hardware_abf'])
        self.assertEqual(result['raw_fields'][0]['raw_value'],128)
        self.assertIsNone(result['raw_fields'][0]['unit'])
        self.assertEqual(result['uninterpreted_sections'][0]['hex'],raw[25:50].hex())
        self.assertEqual(result['uninterpreted_sections'][1]['hex'],raw[56:].hex())
        self.assertEqual(result['header']['frame_type_code'],9)
        self.assertNotIn('frame_slot_ordinal',result)

    def test_stale_values_remain_marked_and_other_profiles_are_unsupported(self):
        result=interpret_funcube(fixture(False))
        self.assertTrue(all(m['source_valid'] is False for m in result['measurements']))
        self.assertEqual(result['measurements'][4]['value'],8123)
        for header in (9,0x49,0xc9,0xbf):
            raw=bytearray(fixture());raw[0]=header
            self.assertEqual(interpret_funcube(raw)['status'],'unsupported_profile')
        for size in (0,55,255,257):
            self.assertEqual(interpret_funcube(bytes(size))['status'],'invalid_length')

    def test_recorded_payload_and_export_roundtrip(self):
        vector=json.loads(Path(__file__).with_name('funcube_fc1_vector.json').read_text())
        raw=bytes.fromhex(vector['payload_hex']);telemetry=interpret_funcube(raw)
        fields={m['id']:m['value'] for m in telemetry['measurements']}
        for key in ('battery_voltage','system_current','reboot_count'):
            self.assertEqual(fields[key],vector['expected'][key])
        self.assertEqual(telemetry['sequence_number'],vector['expected']['sequence_number'])
        self.assertEqual(telemetry['header']['frame_type_code'],9)
        self.assertTrue(telemetry['source_validity']['eps'])
        with tempfile.TemporaryDirectory() as directory:
            frame={'payload_hex':raw.hex(),'telemetry':telemetry}
            trial={'frames':[frame]}
            write_ao40_artifacts(trial,directory)
            self.assertEqual((Path(directory)/frame['payload_artifact']).read_bytes(),raw)
            self.assertEqual(json.loads((Path(directory)/frame['telemetry_artifact']).read_text()),telemetry)
            self.assertFalse(telemetry['identity_confirmed'])
