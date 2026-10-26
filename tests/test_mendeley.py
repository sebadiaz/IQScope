import importlib.util
from pathlib import Path
import unittest
import io
from unittest.mock import patch,Mock

spec = importlib.util.spec_from_file_location('mendeley_probe',Path(__file__).parents[1]/'scripts/mendeley_metadata_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class MendeleyMetadataTests(unittest.TestCase):
    def test_datacite_does_not_invent_absent_identity(self):
        normalized = probe.normalize_datacite({'data':{'attributes':{'doi':'10.17632/example.1','titles':[{'title':'Example'}]}}})
        self.assertEqual(normalized['doi'],'10.17632/example.1')
        self.assertEqual(normalized['rights'],[])
        self.assertEqual(normalized['description_excerpt'],'')

    def test_file_preview_excludes_download_tokens(self):
        result = probe.normalize_mendeley({'id':'x','files':[{'id':'a','filename':'iq.bin','size':123,'download_url':'https://example.org/?private=token'}]})
        self.assertEqual(result['file_count'],1)
        self.assertNotIn('download_url',result['files'][0])

    def test_supporting_files_downloads_only_small_metadata_and_counts_csv(self):
        payload = b'recording_id,signal_type\na,FM\nb,ADS-B\n'
        document = {'id':probe.DATASET,'version':probe.VERSION,'files':[
            {'filename':'metadata.csv','id':'00000000-0000-0000-0000-000000000001','size':len(payload)},
            {'filename':'large_features.csv.gz','id':'00000000-0000-0000-0000-000000000002','size':5000000000}]}
        opener = Mock()
        opener.open.return_value = io.BytesIO(payload)
        with patch.object(probe.urllib.request,'build_opener',return_value=opener):
            result = probe.supporting_files(document)
        self.assertEqual(opener.open.call_count,1)
        self.assertEqual(result[0]['rows'],2)
        self.assertEqual(result[0]['columns'],['recording_id','signal_type'])
        with self.assertRaises(ValueError):
            probe.supporting_files({'id':probe.DATASET,'version':2})

    def test_oversized_supporting_document_is_not_downloaded(self):
        document = {'id':probe.DATASET,'version':probe.VERSION,'files':[{'filename':'metadata.csv','id':'0'*36,'size':1000000}]}
        with patch.object(probe.urllib.request,'build_opener') as opener:
            result = probe.supporting_files(document)
        opener.assert_not_called()
        self.assertIn('error',result[0])

    def test_page_title_and_jsonld_are_separate(self):
        page = probe.PageData()
        page.feed('<title>Example</title><script type="application/ld+json">{"name":"Dataset"}</script><p>Other</p>')
        self.assertEqual(''.join(page.title),'Example')
        self.assertEqual(len(page.schemas),1)
