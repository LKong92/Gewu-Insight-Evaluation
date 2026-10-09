"""Synthetic wire responses solely for qualification of Task A plumbing.

No historical benchmark records, source parser replacement or reference ratings.
The formal collector never imports this module.
"""
import io
import json
from urllib.parse import urlsplit, parse_qs
import requests


def adapter_response(adapter, request, **kwargs):
    u = urlsplit(request.url)
    query = parse_qs(u.query)
    response = requests.Response()
    response.request, response.url, response.connection = request, request.url, adapter
    response.status_code, response.reason = 200, 'OK'
    response.headers['Content-Type'] = 'application/json'
    response.encoding = 'utf-8'
    article = {'DOI': '10.5555/gewu-native-qualification', 'title': ['SYNTHETIC two-dimensional magnetism fixture'],
        'container-title': ['Nature'], 'author': [{'given':'Fixture','family':'Author'}],
        'published-online': {'date-parts': [[2026,9,5]]}, 'type':'journal-article',
        'abstract':'A synthetic qualification article about two-dimensional magnetism. No scientific result.',
        'URL': 'https://www.nature.com/articles/gewu-native-qualification'}
    if u.hostname == 'api.crossref.org':
        text_query = str(query.get('query.bibliographic', [''])[0]).casefold()
        items = [article] if ('1476-4687' in u.path or '0028-0836' in u.path or
            text_query == 'two-dimensional magnetism') else []
        value = {'message': {'items': items, 'total-results': len(items)}}
    elif u.hostname == 'api.openalex.org':
        value = {'meta': {'count':0}, 'results': []}
    elif u.hostname == 'api.semanticscholar.org':
        if '/author/999000001/papers' in u.path:
            value = {'data': [{'paperId':'synthetic-native-author', 'externalIds':{'DOI':'10.5555/gewu-native-author'},
                'title':'SYNTHETIC author publication fixture', 'year':2026, 'publicationDate':'2026-09-05',
                'venue':'Nature', 'authors':[{'authorId':'999000001','name':'Fixture Author'}],
                'abstract':'Synthetic only.', 'url':'https://www.nature.com/articles/gewu-native-author'}]}
        elif '/author/999000001' in u.path:
            value = {'authorId':'999000001', 'name':'Fixture Author', 'affiliations':['Synthetic Institute'],
                'paperCount':1, 'citationCount':0, 'externalIds':{}, 'url':request.url}
        else:
            value = {'data':[], 'total':0}
    elif u.hostname == 'eutils.ncbi.nlm.nih.gov':
        value = {'esearchresult': {'idlist': []}}
    elif u.hostname in ('www.nature.com','nature.com'):
        response.headers['Content-Type'] = 'text/html'
        value = '<html><head><meta name="citation_article_type" content="Article"><meta name="dc.type" content="Article"></head><body><h1>SYNTHETIC qualification only</h1><span>Article</span></body></html>'
    elif u.hostname and (u.hostname.endswith('aps.org') or u.hostname.endswith('arxiv.org')):
        response.headers['Content-Type'] = 'application/xml'
        value = '<?xml version="1.0"?><rss version="2.0"><channel><title>SYNTHETIC empty qualification feed</title></channel></rss>'
    else:
        raise AssertionError('Unspecified qualification source URL: ' + request.url)
    response._content = (value if isinstance(value, str) else json.dumps(value)).encode()
    response._content_consumed = True
    response.raw = io.BytesIO(response._content)
    return response
