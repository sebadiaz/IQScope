import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
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

    def test_public_page_only_records_allowed_filename_hints(self):
        title = probe.PageTitle()
        title.feed('<input id="filename" value="dataset.bin"><input id="requesttoken" value="private"><input name="password" value="private">')
        self.assertEqual(title.file_hints,{'filename':'dataset.bin'})

    def test_new_token_uses_documented_public_dav_without_guessing_passwords(self):
        html = b'<title>public dataset</title>'
        xml = b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dataset/</d:href></d:response></d:multistatus>'
        with patch.object(probe,'fetch',side_effect=[(200,'text/html',html,False),(207,'application/xml',xml,False)]) as fetch:
            result = probe.probe('qrJCWgzQaGPfHPr')
        self.assertEqual(result['status'],'public_metadata_listed')
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url,probe.HOST+'/public.php/dav/files/qrJCWgzQaGPfHPr/')
        self.assertEqual(request.get_header('X-requested-with'),'XMLHttpRequest')
        self.assertIsNone(request.get_header('Authorization'))
        with self.assertRaises(ValueError):
            probe.probe('../invalid')


if __name__ == '__main__':
    unittest.main()
