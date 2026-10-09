#!/usr/bin/env python3
"""Describe observed source pages and limits without treating HTTP success as recall."""
import argparse,hashlib,json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from source_transport import SourceTransport

PAGING={'cursor','offset','cstart','page','retstart'}

def inspect_page(url,status,content):
    u=urlsplit(url);q=parse_qs(u.query);host=u.hostname or ''
    out={'kind':'other_source_or_enrichment','pagination_observation':'not_assessed'}
    if status!=200:
        return dict(out,pagination_observation='not_established_non_200',http_status=status)
    try: data=json.loads(content)
    except (ValueError,UnicodeError):data=None
    items=total=next_value=None;size=None;offset=0
    if host=='api.crossref.org' and isinstance(data,dict) and '/works' in u.path:
        message=data.get('message',{})
        if isinstance(message,dict) and isinstance(message.get('items'),list):
            out['kind']='crossref_collection';items=message['items'];total=message.get('total-results')
            next_value=message.get('next-cursor');size=int(q.get('rows',['0'])[0]) or None
    elif host=='api.openalex.org' and isinstance(data,dict) and isinstance(data.get('results'),list):
        out['kind']='openalex_collection';items=data['results'];total=data.get('meta',{}).get('count')
        next_value=data.get('meta',{}).get('next_cursor');size=int(q.get('per-page',['0'])[0]) or None
    elif host=='api.semanticscholar.org' and isinstance(data,dict) and isinstance(data.get('data'),list):
        out['kind']='semantic_scholar_collection';items=data['data'];total=data.get('total')
        next_value=data.get('next');size=int(q.get('limit',['0'])[0]) or None;offset=int(q.get('offset',['0'])[0])
    elif host=='eutils.ncbi.nlm.nih.gov' and u.path.endswith('esearch.fcgi') and isinstance(data,dict):
        result=data.get('esearchresult',{});items=result.get('idlist')
        out['kind']='pubmed_search';total=result.get('count');size=int(q.get('retmax',['0'])[0]) or None
        offset=int(q.get('retstart',['0'])[0])
    elif host.startswith('scholar.google.') and u.path=='/citations' and 'user' in q:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(content,'html.parser');items=soup.select('.gsc_a_tr')
        out['kind']='google_scholar_profile';size=int(q.get('pagesize',['100'])[0]);offset=int(q.get('cstart',['0'])[0])
        if not items and not soup.select_one('#gsc_a_b #gsc_a_nn'):
            return dict(out,pagination_observation='unexpected_or_access_page_not_empty')
    if items is None:return out
    try:total=int(total) if total is not None else None
    except (TypeError,ValueError):total=None
    count=len(items)
    out.update(raw_page_records=count,requested_page_size=size,reported_total=total,
               response_next=next_value,request_offset=offset)
    if out['kind'] in ('pubmed_search','semantic_scholar_collection') and total is not None and total>offset+count:
        observed='more_records_reported'
    elif next_value is not None and next_value!='' and (size is None or count>=size):
        observed='continuation_advertised'
    elif out['kind']=='google_scholar_profile' and size and count>=size:
        observed='full_page_without_exhaustion_evidence'
    else:observed='terminal_page_observed_under_provider_response'
    out['pagination_observation']=observed
    out['exhaustive_recall_claim']=False
    return out

def summarize(root):
    SourceTransport(root,'replay')  # Integrity validation only; no replay or network.
    attempts=[json.loads(s) for s in (root/'attempts.jsonl').read_text().splitlines()]
    pages=[];groups=defaultdict(list)
    for row in attempts:
        request=row['request'];u=urlsplit(request['url']);params=parse_qs(u.query)
        base=u._replace(query=urlencode([(k,v) for k,values in sorted(params.items()) if k not in PAGING for v in values]),fragment='').geturl()
        response=row.get('response')
        page={'attempt_id':row['attempt_id'],'request_key':row['request_key'],'url':request['url'],
              'parameters':params,'family':base}
        if response:
            content=(root/'blobs'/response['body_sha256']).read_bytes()
            page.update(http_status=response['status'],body_sha256=response['body_sha256'],
                        inspection=inspect_page(request['url'],response['status'],content))
        else:page.update(exception=row['exception'],inspection={'pagination_observation':'not_established_exception'})
        pages.append(page);groups[base].append(page)
    families=[]
    for key,rows in sorted(groups.items()):
        last=rows[-1]
        families.append({'family':key,'attempt_count':len(rows),'unique_request_pages':len({r['request_key'] for r in rows}),
            'last_attempt_id':last['attempt_id'],'last_observation':last['inspection'],
            'failed_attempt_ids':[r['attempt_id'] for r in rows if r.get('http_status',0)>=400 or 'exception' in r],
            'all_attempt_ids':[r['attempt_id'] for r in rows]})
    return {'phase':'archive_source_observation','source_manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
        'attempts':pages,'families':families,'recall_estimated':False,
        'interpretation':['Provider totals may concern pre-filter results rather than the study population.',
          'A terminal page describes this query response, not complete coverage of the scientific literature.',
          'More/continuation/full-page observations remaining at the last request are retained as possible truncation.',
          'Attempts and query families do not increase scientific candidate or scenario denominators.',
          'Native source/monitor outcomes must be reported alongside this transport-level evidence.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--sources',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=summarize(Path(a.sources).resolve())
    with Path(a.output).open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'attempts':len(report['attempts']),'families':len(report['families']),'recall_estimated':False}))

if __name__=='__main__':main()
