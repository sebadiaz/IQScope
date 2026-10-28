import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts=Path(__file__).parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('loraiq_reference',scripts/'loraiq_reference.py')
probe=importlib.util.module_from_spec(spec)
with patch.object(sys,'path',[str(scripts)]+sys.path):
    spec.loader.exec_module(probe)


class LoRaIQReferenceTests(unittest.TestCase):
    def test_selection_uses_metadata_snr_not_payload(self):
        rows=[{'sf':'7','cr':'1','bandwidth':'125000','snr':snr,'payload_base64':payload}
              for snr,payload in [('10','different'),('21','first'),('29','later')]]
        self.assertIs(probe.select_reference(rows),rows[1])
        self.assertIs(probe.select_reference(rows[:1]),rows[0])
        with self.assertRaises(ValueError):
            probe.select_reference([{'sf':'12','cr':'1','bandwidth':'125000','snr':'30'}])

    def test_annotation_paths_cannot_escape_archive_members(self):
        path='./sigmfs/25_01_17-13_40/rrh4/2'
        self.assertEqual(probe.reference_stem({'sigmf_file':path}),path[2:])
        for path in ('../sigmfs/a','https://other.org/a','sigmfs/25_01/../2','sigmfs/25_01/rrh0/2','/sigmfs/25_01/rrh4/2'):
            with self.assertRaises(ValueError):
                probe.reference_stem({'sigmf_file':path})
