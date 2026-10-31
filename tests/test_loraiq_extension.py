import sys
from pathlib import Path
import unittest
from unittest.mock import patch

scripts=Path(__file__).parents[1]/'scripts'
with patch.object(sys,'path',[str(scripts)]+sys.path):
    from loraiq_extension import select_extension


def row(session,member=1,sf='7',bandwidth='125000'):
    return {'sf':sf,'bandwidth':bandwidth,'cr':'1','sigmf_file':f'./sigmfs/{session}/rrh1/{member}',
            'snr':'not used','payload_base64':'not used'}


class LoRaExtensionSelectionTests(unittest.TestCase):
    def test_first_two_sessions_per_configuration_exclude_development(self):
        rows=[row('25_01_17-13_40'),row('25_01_18-10_00'),row('25_01_18-10_00',2),
              row('25_01_19-10_00'),row('25_01_20-10_00'),
              row('25_09_12-14_15',sf='10',bandwidth='250000'),
              row('25_09_12-14_15',2,sf='10',bandwidth='250000'),
              row('25_09_12-15_46',sf='10',bandwidth='250000')]
        selected=select_extension(rows)
        self.assertEqual([r['sigmf_file'] for r in selected],[rows[i]['sigmf_file'] for i in (1,3,5,7)])

    def test_unavailable_configurations_are_not_silently_replaced(self):
        self.assertEqual(select_extension([row('25_01_18-10_00',sf='12')]),[])
        selected=select_extension([row('25_01_18-10_00')])
        self.assertEqual(len(selected),1)

    def test_manifest_pins_first_pass_and_four_distinct_new_sessions(self):
        import json
        manifest=json.loads((Path(__file__).parents[1]/'corpus/loraiq-extension-manifest.json').read_text())
        self.assertEqual(manifest['frozen_decoder_commit'],'793e04f8e494c2e18f73f1b467144c32ea20cb0f')
        self.assertEqual(len(manifest['selected_annotations']),4)
        self.assertEqual(len({r['sigmf_file'].split('/')[2] for r in manifest['selected_annotations']}),4)
        self.assertNotIn('25_01_17-13_40',{r['sigmf_file'].split('/')[2] for r in manifest['selected_annotations']})
