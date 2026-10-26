import importlib.util
from pathlib import Path
import unittest

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

    def test_page_title_and_jsonld_are_separate(self):
        page = probe.PageData()
        page.feed('<title>Example</title><script type="application/ld+json">{"name":"Dataset"}</script><p>Other</p>')
        self.assertEqual(''.join(page.title),'Example')
        self.assertEqual(len(page.schemas),1)
