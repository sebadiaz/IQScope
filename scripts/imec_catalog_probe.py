"""Bounded, read-only inspection of the public imec share. No IQ download."""
import argparse
import base64
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HOST = 'https://cloud.ilabt.imec.be'
TOKEN = 'bqXtdp9QsfXLbb3'
SHARE = HOST+'/index.php/s/'+TOKEN
LIMIT = 256*1024


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != 'https' or target.hostname != 'cloud.ilabt.imec.be':
            raise ValueError('Cross-host or non-HTTPS redirect; inspect it manually before sending share credentials')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PageTitle(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.parts.append(data)


def fetch(request):
    opener = urllib.request.build_opener(SameHostRedirect())
    with opener.open(request, timeout=15) as response:
        content_type = response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
        if content_type not in ('text/html','application/xhtml+xml','application/xml','text/xml','application/json','text/plain'):
            raise ValueError('Endpoint returned non-metadata content; body was not downloaded')
        data = response.read(LIMIT+1)
        if len(data) > LIMIT:
            return response.status, response.headers.get('Content-Type',''), data[:LIMIT], True
        return response.status, response.headers.get('Content-Type',''), data, False


def public_listing(xml):
    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise ValueError('Unexpected XML declarations')
    root = ET.fromstring(xml)
    files = []
    for response in root.findall('{DAV:}response'):
        item = {'href':response.findtext('{DAV:}href')}
        for properties in response.findall('{DAV:}propstat'):
            status = properties.findtext('{DAV:}status','')
            if ' 200 ' not in status:
                continue
            prop = properties.find('{DAV:}prop')
            if prop is None:
                continue
            item.update(name=prop.findtext('{DAV:}displayname'),
                        bytes=prop.findtext('{DAV:}getcontentlength'),
                        content_type=prop.findtext('{DAV:}getcontenttype'),
                        directory=prop.find('{DAV:}resourcetype/{DAV:}collection') is not None)
        files.append(item)
    return files


def probe():
    result = {'source':SHARE, 'checked_utc':datetime.now(timezone.utc).isoformat(),
              'status':'not_inspected', 'files':[], 'observations':[],
              'scope':'public metadata only; no IQ downloaded, no passwords attempted'}
    try:
        status, content_type, body, truncated = fetch(urllib.request.Request(SHARE))
        title = PageTitle()
        if 'html' in content_type:
            title.feed(body.decode('utf-8',errors='replace'))
        result['observations'].append({'method':'GET','status':status,'page_title':''.join(title.parts).strip(),'truncated':truncated})
    except Exception as exc:
        result['observations'].append({'method':'GET','error':str(exc)})
    # Normal public-share WebDAV access: token as username and empty password.
    # A 401/403 is recorded; there are no retries or password guesses.
    auth = base64.b64encode((TOKEN+':').encode()).decode()
    request = urllib.request.Request(HOST+'/public.php/webdav/',method='PROPFIND',
        headers={'Authorization':'Basic '+auth,'Depth':'1','Content-Type':'application/xml'},
        data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:getcontentlength/><d:getcontenttype/><d:resourcetype/></d:prop></d:propfind>')
    try:
        status, content_type, body, truncated = fetch(request)
        result['observations'].append({'method':'PROPFIND','status':status,'truncated':truncated})
        if status == 207 and not truncated:
            result['files'] = public_listing(body)
            result['status'] = 'public_metadata_listed'
        elif truncated:
            result['status'] = 'metadata_exceeds_probe_limit'
    except Exception as exc:
        result['observations'].append({'method':'PROPFIND','error':str(exc)})
    if result['status'] == 'not_inspected':
        result['status'] = 'public_files_not_listed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='corpus-cache/imec/catalog.json')
    args = parser.parse_args()
    result = probe()
    path = Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
