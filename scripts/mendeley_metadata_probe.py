"""Bounded public Mendeley/DataCite metadata inspection, never dataset downloads."""
import argparse
from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

DATASET = 'v2zmysy94r'
VERSION = 1
LIMIT = 1024*1024


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        old,new = urllib.parse.urlsplit(req.full_url),urllib.parse.urlsplit(newurl)
        if new.scheme!='https' or new.hostname!=old.hostname:
            raise ValueError('Cross-host redirect is outside this metadata probe')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class PageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = []
        self.schemas = []
        self.in_title = False
        self.in_schema = False
        self.current = []

    def handle_starttag(self,tag,attrs):
        values = dict(attrs)
        self.in_title |= tag=='title'
        if tag=='script' and values.get('type')=='application/ld+json':
            self.in_schema = True
            self.current = []

    def handle_data(self,data):
        if self.in_title:
            self.title.append(data)
        if self.in_schema:
            self.current.append(data)

    def handle_endtag(self,tag):
        if tag=='title':
            self.in_title = False
        if tag=='script' and self.in_schema:
            self.schemas.append(''.join(self.current))
            self.in_schema = False


def normalize_datacite(document):
    attributes = document.get('data',{}).get('attributes',{})
    return {'doi':attributes.get('doi'),'titles':attributes.get('titles',[]),
            'creators':attributes.get('creators',[]),'publisher':attributes.get('publisher'),
            'publication_year':attributes.get('publicationYear'),'subjects':attributes.get('subjects',[]),
            'rights':attributes.get('rightsList',[]),'types':attributes.get('types',{}),
            'description_excerpt':str((attributes.get('descriptions') or [{}])[0].get('description',''))[:1600],
            'url':attributes.get('url'),'related_identifiers':attributes.get('relatedIdentifiers',[])}


def normalize_mendeley(document):
    data = document.get('data',document)
    if not isinstance(data,dict):
        return {'top_level_type':type(data).__name__}
    files = data.get('files',[])
    if isinstance(files,dict):
        files = files.get('items',[])
    return {'keys':list(data),'id':data.get('id'),'version':data.get('version'),
            'name':data.get('name'),'title':data.get('title'),'doi':data.get('doi'),
            'description_excerpt':str(data.get('description',''))[:1600],
            'licence':data.get('licence',data.get('license')),
            'file_count':len(files) if isinstance(files,list) else None,
            'files':[ {k:f.get(k) for k in ('id','filename','name','size','size_bytes','content_type') if k in f}
                     for f in files[:40] if isinstance(f,dict)] if isinstance(files,list) else []}


def probe():
    doi = f'10.17632/{DATASET}.{VERSION}'
    endpoints = [
        ('datacite','https://api.datacite.org/dois/'+doi),
        ('mendeley_version',f'https://data.mendeley.com/public-api/datasets/{DATASET}/versions/{VERSION}'),
        ('mendeley_dataset',f'https://data.mendeley.com/public-api/datasets/{DATASET}'),
        ('page',f'https://data.mendeley.com/datasets/{DATASET}/{VERSION}')]
    result = {'dataset_id':DATASET,'version':VERSION,'checked_utc':datetime.now(timezone.utc).isoformat(),
              'scope':'public metadata only, no dataset files downloaded','observations':[]}
    for kind,url in endpoints:
        item = {'kind':kind,'url':url}
        try:
            request = urllib.request.Request(url,headers={'User-Agent':'IQScope-metadata-probe/0.15','Accept':'application/json' if kind!='page' else 'text/html'})
            with urllib.request.build_opener(SameHostRedirect()).open(request,timeout=20) as response:
                content_type = response.headers.get('Content-Type','').lower()
                if not any(t in content_type for t in ('application/json','text/html','application/ld+json')):
                    raise ValueError('Endpoint did not return metadata; body not downloaded')
                body = response.read(LIMIT+1)
                item.update(http_status=response.status,content_type=content_type,bytes_read=len(body),truncated=len(body)>LIMIT)
            if len(body)>LIMIT:
                result['observations'].append(item)
                continue
            item['sha256'] = hashlib.sha256(body).hexdigest()
            if 'json' in content_type:
                document = json.loads(body)
                item['metadata'] = normalize_datacite(document) if kind=='datacite' else normalize_mendeley(document)
            else:
                page = PageData()
                page.feed(body.decode('utf-8',errors='replace'))
                item['page_title'] = ''.join(page.title).strip()
                item['jsonld'] = []
                for schema in page.schemas[:3]:
                    value = json.loads(schema)
                    if isinstance(value,dict):
                        item['jsonld'].append({k:value.get(k) for k in ('@type','name','description','license','keywords') if k in value})
        except urllib.error.HTTPError as exc:
            item.update(http_status=exc.code,error=str(exc))
        except Exception as exc:
            item['error'] = str(exc)
        result['observations'].append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='corpus-cache/mendeley/metadata.json')
    args = parser.parse_args()
    result = probe()
    path = Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
