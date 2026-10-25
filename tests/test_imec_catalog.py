import importlib.util
from pathlib import Path
import unittest
import urllib.request

spec = importlib.util.spec_from_file_location('imec_probe',Path(__file__).parents[1]/'scripts/imec_catalog_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class CatalogTests(unittest.TestCase):
    def test_webdav_lists_only_successful_properties(self):
        body = b'''<d:multistatus xmlns:d="DAV:"><d:response>
        <d:href>/public.php/webdav/LoRa/</d:href><d:propstat>
        <d:prop><d:displayname>LoRa</d:displayname><d:resourcetype><d:collection/></d:resourcetype></d:prop>
        <d:status>HTTP/1.1 200 OK</d:status></d:propstat><d:propstat>
        <d:prop><d:getcontentlength>999</d:getcontentlength></d:prop><d:status>HTTP/1.1 404 Not Found</d:status>
        </d:propstat></d:response></d:multistatus>'''
        result = probe.public_listing(body)
        self.assertEqual(result[0]['name'],'LoRa')
        self.assertTrue(result[0]['directory'])
        self.assertIsNone(result[0]['bytes'])

    def test_xml_external_entities_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'XML declarations'):
            probe.public_listing(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x/>')

    def test_share_credentials_cannot_follow_external_redirect(self):
        request = urllib.request.Request(probe.HOST+'/public.php/webdav/')
        with self.assertRaisesRegex(ValueError,'Cross-host'):
            probe.SameHostRedirect().redirect_request(request,None,302,'',{},'https://example.org/')

    def test_title_does_not_collect_other_page_text(self):
        title = probe.PageTitle()
        title.feed('<html><title>Public dataset</title><body>other text</body></html>')
        self.assertEqual(''.join(title.parts),'Public dataset')


if __name__ == '__main__':
    unittest.main()
