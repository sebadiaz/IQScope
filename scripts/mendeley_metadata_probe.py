"""Bounded public Mendeley/DataCite inspection; no bulk feature-table or IQ downloads."""
import argparse
import csv
import io
import re
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
            'name':data.get('name'),'title':data.get('title'),'doi':data.get('doi',{}).get('id') if isinstance(data.get('doi'),dict) else data.get('doi'),
            'description_excerpt':str(data.get('description',''))[:1600],
            'licence':data.get('data_licence',data.get('licence',data.get('license'))),
            'related_links':data.get('related_links',[]),
            'description_zenodo_urls':re.findall(r'https?://(?:www\.)?zenodo\.org/[^\s<>\"\)]+',str(data.get('description',''))),
            'file_count':len(files) if isinstance(files,list) else None,
            'files':[ {k:f.get(k) for k in ('id','filename','name','size','size_bytes','content_type') if k in f}
                     for f in files[:40] if isinstance(f,dict)] if isinstance(files,list) else []}


class FileRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ''
        if parsed.scheme!='https' or not (host=='data.mendeley.com' or host.endswith('.s3.eu-west-1.amazonaws.com')):
            raise ValueError('Unexpected supporting-file download host')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def supporting_files(document):
    if document.get('id')!=DATASET or document.get('version')!=VERSION:
        raise ValueError('Public API identity/version differs from the requested source')
    results = []
    for file in document.get('files',[]):
        name = file.get('filename')
        if name not in ('README.txt','metadata.csv','feature_description.csv'):
            continue
        item = {'name':name,'declared_bytes':file.get('size')}
        try:
            size = int(file['size'])
            if not 0<size<=65536 or not re.fullmatch(r'[a-fA-F0-9-]{36}',file['id']):
                raise ValueError('Supporting file exceeds the small metadata contract')
            url = f"https://data.mendeley.com/public-files/datasets/{DATASET}/files/{file['id']}/file_downloaded"
            with urllib.request.build_opener(FileRedirect()).open(urllib.request.Request(url),timeout=20) as response:
                body = response.read(65537)
            if len(body)!=size or len(body)>65536:
                raise ValueError('Supporting file size differs or exceeds the 64 KiB bound')
            text = body.decode('utf-8-sig')
            item.update(bytes_read=len(body),sha256=hashlib.sha256(body).hexdigest(),source_endpoint=url)
            if name.endswith('.csv'):
                reader = csv.DictReader(io.StringIO(text))
                rows = list(reader)
                item['columns'] = reader.fieldnames
                item['rows'] = len(rows)
            else:
                item['zenodo_urls'] = re.findall(r'https?://(?:www\.)?zenodo\.org/[^\s<>\"\)]+',text)
                item['relevant_lines'] = [line.strip()[:300] for line in text.splitlines() if re.search(r'IQ|raw|Zenodo|licen|record|column',line,re.I)][:15]
        except Exception as exc:
            item['error'] = str(exc)
        results.append(item)
    return results


def probe():
    doi = f'10.17632/{DATASET}.{VERSION}'
    endpoints = [
        ('datacite','https://api.datacite.org/dois/'+doi),
        ('mendeley_version',f'https://data.mendeley.com/public-api/datasets/{DATASET}/versions/{VERSION}'),
        ('mendeley_dataset',f'https://data.mendeley.com/public-api/datasets/{DATASET}'),
        ('page',f'https://data.mendeley.com/datasets/{DATASET}/{VERSION}')]
    result = {'dataset_id':DATASET,'version':VERSION,'checked_utc':datetime.now(timezone.utc).isoformat(),
              'scope':'public metadata and small supporting documents only; no bulk feature tables or IQ downloaded','observations':[]}
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
                if kind=='mendeley_dataset':
                    item['supporting_files'] = supporting_files(document)
            else:
                page = PageData()
                page.feed(body.decode('utf-8',errors='replace'))
                item['page_title'] = ''.join(page.title).strip()
                item['jsonld'] = []
                for schema in page.schemas[:3]:
                    value = json.loads(schema)
                    if isinstance(value,dict):
                        item['jsonld'].append({k:value.get(k) for k in ('@type','name','license','keywords') if k in value})
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
