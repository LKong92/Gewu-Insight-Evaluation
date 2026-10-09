#!/usr/bin/env python3
"""Run deterministic product cases in an isolated, write-guarded process.

Qualification only until the separate formal design/data locks are implemented.
Product code is imported unchanged from the frozen worktree, never the live App.
"""
import argparse
from contextlib import ExitStack
import datetime as dt
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import traceback
from urllib.parse import urlsplit, unquote
from types import SimpleNamespace
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        f.write('\n')


def guard_writes(root):
    root = root.resolve()
    def safe(path):
        if isinstance(path, int) or path is None:
            return True
        return Path(os.fsdecode(path)).resolve().is_relative_to(root)
    def safe_at(path, dir_fd=None):
        if isinstance(path,int) or dir_fd in (None,-1) or Path(os.fsdecode(path)).is_absolute():
            return safe(path)
        # Python emits basename + directory descriptor for secure rmtree and
        # client-copy release. Resolve that descriptor, never guess from cwd.
        if sys.platform=='darwin':
            import fcntl
            directory=os.fsdecode(fcntl.fcntl(dir_fd,50,b'\0'*1024).split(b'\0',1)[0])
        else:
            directory=os.readlink('/proc/self/fd/'+str(dir_fd))
        return safe(Path(directory)/os.fsdecode(path))
    def audit(event, args):
        if event == 'sqlite3.connect':
            dbpath=args[0]
            if isinstance(dbpath,bytes):dbpath=os.fsdecode(dbpath)
            if isinstance(dbpath,str) and dbpath.startswith('file:'):
                dbpath=unquote(urlsplit(dbpath).path)
            if dbpath != ':memory:' and not safe(dbpath):
                raise PermissionError('Benchmark blocked SQLite outside isolated run root: '+str(dbpath)+'; allowed='+str(root))
        elif event == 'open':
            path, mode, flags = args
            writing = bool((flags or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and not safe(path):
                raise PermissionError('Benchmark blocked write outside isolated run root: ' + str(path))
            if isinstance(path, (str, bytes)):
                full = Path(os.fsdecode(path)).resolve()
                live = Path(os.environ.get('GEWU_FORBIDDEN_PRODUCTION_ROOT', '/__forbidden_production__'))
                if any(full.is_relative_to(live / d) for d in ('data', 'reports', 'metadata')):
                    raise PermissionError('Benchmark must not read production data')
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'):
            fd_index={'os.remove':1,'os.rmdir':1,'os.mkdir':2,'os.chmod':2,'os.utime':3}[event]
            if not safe_at(args[0],args[fd_index] if len(args)>fd_index else None):
                raise PermissionError('Benchmark blocked external filesystem mutation')
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            source_fd=args[2] if event!='os.symlink' and len(args)>2 else None
            target_fd=args[3] if event!='os.symlink' and len(args)>3 else args[2] if event=='os.symlink' and len(args)>2 else None
            if not safe_at(args[1],target_fd) or (event != 'os.symlink' and not safe_at(args[0],source_fd)):
                raise PermissionError('Benchmark blocked external filesystem move/link')
        elif event == 'subprocess.Popen' or event == 'os.system':
            raise PermissionError('No subprocess or desktop launch in this engineering qualification')
        elif event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
                raise PermissionError('No remote network in synthetic engineering cases')
        elif event == 'socket.bind':
            address = args[1]
            if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] != 0:
                raise PermissionError('Only an ephemeral isolated loopback server is allowed')
    sys.addaudithook(audit)


class Harness:
    def __init__(self, root):
        from paper_monitor import ui_server, storage
        self.root, self.ui, self.sm = root, ui_server, storage
        self.path = root / 'state.sqlite'
        self.stack = ExitStack()
        self.trace = []
        for name in ('LIBRARY_LOCAL_COPY_ROOT','SPACES_LOCAL_COPY_ROOT','MY_PUBLICATIONS_LOCAL_COPY_ROOT',
                     'ASSOCIATED_FILES_ROOT','DEFAULT_PDF_DIR'):
            self.stack.enter_context(patch.object(ui_server, name, root / name))
        self.s = storage.Storage(self.path)
        self.http = None

    def close(self):
        if self.http:
            self.http.shutdown(); self.http.server_close(); self.http_thread.join()
        self.s.close(); self.stack.close()

    def reopen(self):
        self.s.close(); self.s = self.sm.Storage(self.path)
        self.trace.append({'operation':'Storage.close/reopen'})

    def call(self, fn, *args, **kwargs):
        self.trace.append({'operation': fn.__module__ + '.' + fn.__qualname__})
        return fn(*args, **kwargs)

    def paper(self, pid='work', **overrides):
        value = dict(paper_id=pid, doi='10.5555/v4-'+pid, title='Benchmark quantum material',
            journal='Physical Review B', source='benchmark_synthetic', raw={'authors':['A. Researcher']})
        value.update(overrides)
        self.call(self.s.upsert_paper, value)
        return value['paper_id']

    def pdf(self, variant='clean', tag='same'):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, ArrayObject, NumberObject, TextStringObject
        if variant == 'empty': return b''
        if variant == 'text':
            # Here text is an annotation fixture; invalid plain text has own path.
            pass
        w = PdfWriter()
        for _ in range(2 if variant == 'two_pages' else 0 if variant == 'zero_pages' else 1):
            w.add_blank_page(width=612, height=792)
        w.add_metadata({'/Title':'V4 SYNTHETIC ENGINEERING '+tag})
        if variant in ('text','highlight','link'):
            annotation = DictionaryObject({NameObject('/Type'):NameObject('/Annot'),
                NameObject('/Subtype'):NameObject({'text':'/Text','highlight':'/Highlight','link':'/Link'}[variant]),
                NameObject('/Rect'):ArrayObject([NumberObject(v) for v in (10,10,100,40)]),
                NameObject('/Contents'):TextStringObject('SYNTHETIC annotation')})
            if variant == 'highlight':
                annotation[NameObject('/QuadPoints')] = ArrayObject([NumberObject(v) for v in (10,40,100,40,10,10,100,10)])
            if variant == 'link':
                annotation[NameObject('/A')] = DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject('https://example.invalid')})
            w.add_annotation(0, annotation)
        if variant in ('empty_password','password'):
            w.encrypt('' if variant == 'empty_password' else 'synthetic-password')
        out = io.BytesIO(); w.write(out)
        return out.getvalue()

    def file(self, pid, kind='preprint', variant='clean', tag='same', name=None, attach=False):
        content = b'invalid synthetic data' if kind == 'invalid_file' else self.pdf(variant,tag)
        name = name or kind+'-'+tag+'.pdf'
        if attach:
            return self.call(self.ui.attach_file_to_paper,self.s,paper_id=pid,filename=name,content=content,file_type=kind)
        path = self.root / 'input_files' / pid / name
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        return self.call(self.s.create_paper_resource,paper_id=pid,stored_path=str(path),file_type=kind,
            file_source='user_import',sha256=hashlib.sha256(content).hexdigest(),annotation_state='unannotated')

    def resources(self,pid='work'):
        return self.s.list_paper_resources(pid,ensure_primary=False)

    def default(self,pid='work'):
        return (self.call(self.s.resolve_default_paper_resource,pid) or {}).get('file_type')

    def snapshot(self):
        self.s.conn.commit()
        files = [{'path':str(p.relative_to(self.root)),'sha256':sha(p),'bytes':p.stat().st_size}
                 for p in sorted(self.root.rglob('*')) if p.is_file() and p.suffix in ('.pdf','.md','.csv')]
        tables = {}
        for name in ('papers','resources','library_items','publication_notices','publication_notice_files','paper_aliases','paper_identity_history'):
            tables[name] = [dict(r) for r in self.s.conn.execute('SELECT * FROM '+name)]
        return {'tables':tables,'files':files,'foreign_key_errors':[tuple(r) for r in self.s.conn.execute('PRAGMA foreign_key_check')]}

    def serve(self):
        if self.http: return
        path = self.path
        class Handler(self.ui.PaperMonitorUiHandler):
            configured_db_path = path
            def log_message(self,*args): pass
        self.http = self.ui.FastLocalThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever,daemon=True);self.http_thread.start()

    def token(self, scopes=None, roots=None, selection=None):
        from paper_monitor import ai_store
        from paper_monitor.ai_contract import WRITE_SCOPES
        self.s.set_setting('ai_access_enabled','true')
        created = ai_store.create_connection(self.s,{'name':'V4 disposable fixture',
            'scopes':scopes if scopes is not None else ['papers:read','files:read','folders:read',*set(WRITE_SCOPES.values())],
            'write_folder_ids': [1] if roots is None else roots,'selection': selection or {'kind':'saved'}})
        return created['token'],created['connection']['id']

    def http_call(self, token, name, args):
        self.serve()
        c = http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=20)
        c.request('POST','/api/v1/tools/'+name,json.dumps(args),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=c.getresponse();status=response.status;value=json.loads(response.read());c.close()
        # Authentication material never enters traces or reviewer evidence.
        self.trace.append({'operation':'HTTP /api/v1/tools/'+name,'status':status,'request':args,'response':value})
        return status,value

    def upload(self, token, content=None, request_id='fixture-upload-0001'):
        from paper_monitor import ai_uploads
        content=self.pdf() if content is None else content
        value=self.call(ai_uploads.receive,self.s,'Bearer '+token,io.BytesIO(content),name='fixture.pdf',
            length=len(content),digest=hashlib.sha256(content).hexdigest(),retry_id=request_id)
        return value['upload_id']


def identity_observation(h, x):
    pid=h.paper();before=h.s.get_paper(pid)
    incoming={'paper_id':pid,'doi':'10.5555/v4-work','title':x.get('title',before['title']),
        'journal':x.get('journal',before['journal']),'url':x.get('url',''),'source':'second_provider',
        'raw':{'authors':x.get('authors',['A. Researcher'])}}
    return bool(h.call(h.s.upsert_paper,incoming))


def canonical_identity(h,x):
    variant=x['variant']
    doi='10.5555/v4-shared'
    if variant == 'concurrent':
        from concurrent.futures import ThreadPoolExecutor
        def one(pid):
            s=h.sm.Storage(h.path)
            try: return s.upsert_paper({'paper_id':pid,'doi':doi,'title':'Concurrent benchmark work','journal':'Fixture Journal','raw':{'authors':['A. Researcher']},'source':'synthetic'})
            finally:s.close()
        with ThreadPoolExecutor(2) as pool:list(pool.map(one,('one','two')))
        h.trace.append({'operation':'two concurrent Storage.upsert_paper connections'})
    else:
        h.paper('one',doi=None if variant in ('arxiv','no_identifier') else doi,
                raw={'arxiv_id':'2601.12345','authors':['A. Researcher']} if variant=='arxiv' else {'authors':['A. Researcher']})
        change={}
        if variant=='normalized_doi': change['doi']='https://doi.org/10.5555/V4-SHARED'
        elif variant=='different_doi':change['doi']='10.5555/different'
        elif variant in ('no_identifier','late_doi'):change['doi']=None
        elif variant=='arxiv':change.update(doi=None,raw={'arxiv_id':'2601.12345','authors':['A. Researcher']})
        elif variant=='conflict':change.update(doi=doi,title='Unrelated ocean biology',journal='Marine Ecology',raw={'authors':['Z. Ocean']})
        else:change['doi']=doi
        h.paper('two',**change)
        if variant=='late_doi':
            old=h.s.get_paper('two')['storage_key']
            h.call(h.s.refresh_paper_metadata,'two',{'paper_id':'two','doi':doi,'title':'Benchmark quantum material','journal':'Physical Review B','raw':{'authors':['A. Researcher']},'source':'synthetic'})
            return h.s.paper_for_key(old)['paper_id']=='one' and h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0]==1
    return h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0]


def default_case(h,x,preserve=False):
    pid=h.paper();rows=[]
    for n,kind in enumerate(x['types']):
        rows.append(h.file(pid,kind,tag=str(n)))
        if n==0 and (isinstance(x.get('manual'),int) or x.get('manual')=='clear_after'):
            h.call(h.s.set_preferred_paper_resource,pid,rows[0]['id'])
    if x.get('manual')=='clear_after':h.call(h.s.set_preferred_paper_resource,pid,None)
    if preserve:return {'types':sorted(r['file_type'] for r in h.resources(pid)),'default':h.default(pid)}
    return h.default(pid)


def notice_case(h,x):
    from paper_monitor import publication_notices as notices
    pid=h.paper();variant=x['variant'];own='10.5555/v4-notice'
    if variant=='original_flag':return bool(h.call(notices.describe,{'title':'Benchmark original research','raw':{'is_retracted':True,'update-by':[{'DOI':own}]}}))
    if variant=='corrected_full':return bool(h.call(notices.describe,{'title':'Corrected full article about benchmark material','raw':{'file_type':'corrected_published_version'}}))
    targets=[] if variant=='unresolved' else ['10.5555/v4-work','10.5555/second'] if variant=='ambiguous' else [own] if variant=='self_target' else ['10.5555/v4-work']
    paper={'paper_id':'notice','doi':own,'title':x['title'],'source':'synthetic','raw':{'publication_notice':{'related_dois':targets,'evidence_url':'https://example.invalid/notice'}}}
    h.call(notices.record_for_ingestion,h.s,paper);h.s.conn.commit()
    if variant=='repeat':h.call(notices.record_for_ingestion,h.s,paper);h.s.conn.commit()
    if variant=='relation_conflict':
        before=[dict(r) for r in h.s.conn.execute('SELECT * FROM publication_notices')]
        paper['raw']['publication_notice']['related_dois']=['10.5555/other']
        try:h.call(notices.record_for_ingestion,h.s,paper)
        except notices.NoticeReviewRequired:return before==[dict(r) for r in h.s.conn.execute('SELECT * FROM publication_notices')]
        return False
    event=dict(h.s.conn.execute('SELECT * FROM publication_notices').fetchone())
    return {'papers':h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],
            'events':h.s.conn.execute('SELECT count(*) FROM publication_notices').fetchone()[0],
            'status':event['status'],'kind':event['kind']}


def annotation_case(h,x):
    pid=h.paper();h.s.add_library_item(paper_id=pid,folder_id=1)
    if x['variant']=='coexist':
        h.file(pid,attach=True,name='clean.pdf')
        h.file(pid,variant=x['content'],attach=True,name='second.pdf')
        return len(h.resources())
    row=h.file(pid,variant=x['content'],attach=True)
    if x['variant']=='detect':return row['annotation_state']
    state='annotated' if x['variant']=='override_annotated' else 'unannotated'
    h.call(h.ui.update_paper_resource_role,h.s,pid,row['id'],'preprint',annotation_state=state)
    if x['variant']=='override_restart':h.reopen()
    refreshed=h.call(h.ui.refresh_paper_resource_fingerprints,h.s,pid)
    return refreshed[0]['annotation_state']


def preservation_case(h,x):
    pid=h.paper();variant=x['variant']
    if variant=='metadata_only':
        h.call(h.s.refresh_paper_metadata,pid,{'paper_id':pid,'doi':'10.5555/v4-work','title':'Benchmark quantum material','journal':'Physical Review B','pdf_url':'https://example.invalid/file.pdf','source':'metadata','raw':{'authors':['A. Researcher']}})
        return len(h.resources())
    if variant=='versions':
        rows=[h.file(pid,kind,tag=str(i)) for i,kind in enumerate(x['types'])]
        return sorted(r['file_type'] for r in h.resources())==sorted(x['types']) and all(Path(r['stored_path']).read_bytes()==h.pdf(tag=str(i)) for i,r in enumerate(rows))
    h.s.add_library_item(paper_id=pid,folder_id=1)
    first=h.file(pid,attach=True,name='first.pdf',tag='aaaa')
    original=Path(first['stored_path']).read_bytes()
    if variant=='same_path':
        again=h.call(h.s.create_paper_resource,paper_id=pid,stored_path=str(Path(first['stored_path']).parent/'.'/Path(first['stored_path']).name),file_type='preprint')
        return again['id']==first['id']
    if variant=='different_work':
        second=h.paper('other');h.s.add_library_item(paper_id=second,folder_id=1)
        h.file(second,attach=True,tag='aaaa')
        return h.s.conn.execute('SELECT count(*) FROM resources').fetchone()[0]
    if variant=='manual_default':h.call(h.s.set_preferred_paper_resource,pid,first['id'])
    if variant=='restart':h.reopen()
    if variant=='concurrent':
        from concurrent.futures import ThreadPoolExecutor
        def one(n):
            s=h.sm.Storage(h.path)
            try:return h.ui.attach_file_to_paper(s,paper_id=pid,filename='concurrent-%d.pdf'%n,content=original,file_type='preprint')
            finally:s.close()
        with ThreadPoolExecutor(2) as pool:list(pool.map(one,(1,2)))
        h.trace.append({'operation':'two concurrent attach_file_to_paper connections'})
        return len(h.resources())
    tag='bbbb' if variant in ('same_size','same_name') else 'aaaa'
    if variant=='same_size' and len(h.pdf(tag=tag))!=len(original):raise ValueError('same-size fixture contract failed')
    again=h.file(pid,attach=True,tag=tag,name='first.pdf' if variant=='same_name' else 'renamed.pdf')
    if variant in ('same_size','same_name'):return len(h.resources())
    if variant=='renamed':return len(h.resources())==1 and Path(first['stored_path']).read_bytes()==original
    if variant=='manual_default':return h.s.resolve_default_paper_resource(pid)['id']==first['id'] and len(h.resources())==1
    return {'count':len(h.resources()),'same_id':again['id']==first['id']}


def pdf_validation(h,x):
    from paper_monitor.pdf_utils import is_valid_pdf_bytes
    kind=x['content'];clean=h.pdf()
    invalid={'text':b'not a pdf','header_only':b'%PDF-1.7','fake_objects':b'%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF',
        'half':clean[:len(clean)//2],'missing_eof':clean.replace(b'%%EOF',b''),'fake_prefix':b'prefix'+clean[:40]+b'%%EOF',
        'html':b'<html>Please log in</html>','broken_xref':b'%PDF-1.7\nxref\n0 2\ninvalid\ntrailer\n<< /Root 99 0 R >>\nstartxref\n9\n%%EOF'}
    content=invalid[kind] if kind in invalid else h.pdf(kind)
    path=h.root/'parser-input.pdf';path.write_bytes(content)
    return bool(h.call(is_valid_pdf_bytes,content))


def metadata_correction(h,x):
    from paper_monitor import metadata_refresh as work
    variant=x['variant'];pid=h.paper();row=h.file(pid);h.s.add_library_item(paper_id=pid,folder_id=1)
    h.s.set_preferred_paper_resource(pid,row['id']);before=h.s.get_paper(pid);original=Path(row['stored_path']).read_bytes()
    target='10.5555/v4-corrected'
    def preserved():
        current=h.s.get_paper(pid)
        return all(current[k]==before[k] for k in ('paper_id','storage_key','preferred_resource_id','preferred_resource_manual')) and Path(row['stored_path']).read_bytes()==original and len(h.resources())==1
    if variant=='collision':
        h.paper('other',doi=target,title='Other owned work')
        try:h.call(work.save_doi,h.s,pid,target)
        except ValueError:return preserved() and h.s.get_paper(pid)==before
        return False
    if variant=='invalid':
        try:h.call(work.save_doi,h.s,pid,'not a DOI')
        except ValueError:return preserved() and h.s.get_paper(pid)==before
        return False
    if variant=='arxiv_edit':
        h.call(h.ui.update_manual_preprint_identifier,h.s,pid,'2601.12345')
        return preserved() and h.ui.arxiv_identifier_for_paper(h.s.get_paper(pid))=='2601.12345'
    if x.get('clear_first'):
        h.call(work.save_doi,h.s,pid,'')
        h.trace.append({'operation':'read_after_manual_doi_clear','observed_doi':h.s.get_paper(pid)['doi']})
        if h.s.get_paper(pid)['doi']:return False
    h.call(work.save_doi,h.s,pid,'' if variant=='clear_doi' else target)
    if variant in ('save_doi','clear_doi','pending'):
        current=h.s.get_paper(pid)
        return preserved() and (not current['doi'] if variant=='clear_doi' else current['doi']==target) and (variant!='pending' or h.ui.parse_raw_json(current)['manual_identifier_correction']['status']=='pending')
    remote={'paper_id':'remote','doi':target,'title':'Verified corrected benchmark bibliography','journal':'Verified Fixture Journal','abstract':'New synthetic metadata','source':'crossref','url':'https://doi.org/'+target,'raw':{'DOI':target,'authors':['A. Researcher']}}
    if variant=='mismatched_refresh':remote.update(doi='10.5555/wrong-response');remote['raw']['DOI']=remote['doi']
    def response(*a,**kw):
        if variant=='stale_refresh':h.call(work.save_doi,h.s,pid,'10.5555/concurrent-edit')
        return None if variant=='missing_refresh' else dict(remote)
    # Explicit metadata-provider fixture boundary. This is NOT an end-to-end
    # transport acquisition test and does not contribute Task A source evidence.
    with ExitStack() as stack:
        stack.enter_context(patch.object(h.ui,'publication_metrics_metadata_from_doi',side_effect=response))
        for name,value in {'fetch_arxiv_by_id':None,'pubmed_metadata_from_doi':None,'ads_api_token':'',
            'semantic_scholar_request':SimpleNamespace(json=lambda:{}),'openalex_request':SimpleNamespace(json=lambda:{'results':[]})}.items():
            stack.enter_context(patch.object(h.ui,name,return_value=value))
        h.trace.append({'fixture_boundary':'metadata provider return values; product refresh/identity/storage unmodified'})
        try:
            h.call(work.refresh,h.s,pid,mode='quick' if variant=='quick_refresh' else 'full')
            if variant=='repeat_refresh':h.call(work.refresh,h.s,pid)
        except ValueError:
            if variant=='stale_refresh':return preserved() and h.s.get_paper(pid)['doi']=='10.5555/concurrent-edit' and h.s.get_paper(pid)['title']==before['title']
            raise
    current=h.s.get_paper(pid)
    good=preserved() and current['title']==(before['title'] if variant in ('missing_refresh','mismatched_refresh') else remote['title'])
    if variant=='repeat_refresh':good=good and len(h.ui.parse_raw_json(current).get('manual_identifier_metadata_history',[]))==1
    return good


def mcp_import(h,x):
    from paper_monitor import ai_store
    variant=x['variant']
    if variant=='private_cache':
        anchor=h.paper('grant_anchor',doi='10.5555/authorized-anchor')
        h.s.add_library_item(paper_id=anchor,folder_id=1)
        token,cid=h.token(selection={'kind':'papers','keys':[h.s.get_paper(anchor)['storage_key']]})
    else:token,cid=h.token(scopes=['papers:read'] if variant=='file_scope' else None)
    meta=dict(title='V4 supplied metadata',authors=['Fixture Researcher'],journal='Fixture Journal',
        publication_type='journal_article',publication_date='2026-09-20',doi='10.5555/v4-import',arxiv_id=None,
        source_url='https://example.invalid/work',abstract='Synthetic engineering metadata')
    args={'folder_id':1,'metadata':meta,'request_id':'v4-import-request-0001'}
    if variant=='destination_denied':args['folder_id']=h.s.create_library_root_folder(name='Unshared private root')['id']
    if variant=='private_cache':
        pid=h.paper('cached',doi=meta['doi'],title=meta['title'],journal=meta['journal'],raw={'authors':meta['authors']})
        folder=h.s.create_library_root_folder(name='Unshared private root')['id'];h.s.add_library_item(paper_id=pid,folder_id=folder)
    if variant=='public_cache':
        pid=h.paper('cached',doi=meta['doi'],title=meta['title'],journal=meta['journal'],source='crossref',raw={'authors':meta['authors']})
        old_key=h.s.get_paper(pid)['storage_key']
    if variant=='invalid_upload':args.update(upload_id='absent-upload',file_type='published_version')
    if variant=='missing_metadata':args['metadata']=dict(meta);args['metadata'].pop('authors')
    if variant=='revoked':
        h.s.conn.execute('UPDATE ai_connections SET revoked_at=? WHERE id=?',('2026-10-01T00:00:00+00:00',cid));h.s.conn.commit()
    before=h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0]
    status,result=h.http_call(token,'import_paper',args)
    if variant in ('destination_denied','private_cache','invalid_upload','missing_metadata','revoked','file_scope'):
        expected={'destination_denied':403,'private_cache':403,'missing_metadata':400,'revoked':401,'file_scope':403}
        return (status==expected[variant] if variant in expected else status>=400) and h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0]==before
    if status!=200:return False
    key=result['gewu_key'];pid=h.s.paper_for_key(key)['paper_id']
    if variant=='metadata_only':return result.get('file') is None and len(h.resources(pid))==0
    if variant=='public_cache':return key==old_key and h.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0]==1
    if variant=='retry':
        again_status,again=h.http_call(token,'import_paper',args)
        return again_status==200 and again['gewu_key']==key and len(h.resources(pid))==0 and h.s.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?',(pid,)).fetchone()[0]==1
    if variant=='request_conflict':
        original_title=h.s.get_paper(pid)['title']
        changed={**args,'metadata':{**meta,'title':'Changed request payload'}}
        s,r=h.http_call(token,'import_paper',changed)
        return s==409 and r.get('code')=='request_conflict' and h.s.get_paper(pid)['title']==original_title
    if variant=='manual_default':
        first=h.file(pid,attach=True,tag='original');h.call(h.ui.set_preferred_paper_file,h.s,pid,first['id'])
        original=Path(h.s.get_paper_resource(first['id'])['stored_path']).read_bytes()
    upload=h.upload(token,content=h.pdf(tag='new_pdf'))
    later={**args,'request_id':'v4-import-request-0002','upload_id':upload,'file_type':'published_version'}
    s,r=h.http_call(token,'import_paper',later)
    if variant=='later_pdf':return s==200 and r['gewu_key']==key and len(h.resources(pid))==1
    if variant=='manual_default':return s==200 and r['gewu_key']==key and len(h.resources(pid))==2 and h.s.resolve_default_paper_resource(pid)['id']==first['id'] and Path(h.s.get_paper_resource(first['id'])['stored_path']).read_bytes()==original
    raise ValueError('Unimplemented MCP variant '+variant)


def execute(h, case):
    op,x=case['operation'],case['inputs']
    if op=='identity_observation':return identity_observation(h,x)
    if op=='canonical_identity':return canonical_identity(h,x)
    if op=='legacy_type':return h.call(h.sm.legacy_paper_file_type,x['role'],x['version'],display_name=x['name'],parse_status=x['parse'])
    if op=='normalize_type':return h.call(h.sm.normalize_paper_file_type,x['value'])
    if op=='default':return default_case(h,x)
    if op=='notice_files':return default_case(h,x,True)
    if op=='notice_event':return notice_case(h,x)
    if op=='annotation':return annotation_case(h,x)
    if op=='preservation':return preservation_case(h,x)
    if op=='pdf_validation':return pdf_validation(h,x)
    if op=='source':return h.call(h.sm.inferred_paper_file_source,x['url'],x['via'])[0]
    if op=='metadata_correction':return metadata_correction(h,x)
    if op=='mcp_import':return mcp_import(h,x)
    raise ValueError('No runner for '+op)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--product-root',required=True);p.add_argument('--cases',required=True)
    p.add_argument('--output',required=True);p.add_argument('--families',nargs='*');a=p.parse_args()
    product=Path(a.product_root).resolve();spec=json.loads(Path(a.cases).read_text());root=Path(a.output).resolve()
    if root.exists():raise FileExistsError('Run roots are immutable: '+str(root))
    if product==Path(os.environ.get('GEWU_FORBIDDEN_PRODUCTION_ROOT', '/__forbidden_production__')) or not (product/'benchmarks/evaluation/control/baseline.json').is_file():
        raise ValueError('Require the isolated frozen benchmark product worktree')
    baseline=json.loads((product/'benchmarks/evaluation/control/baseline.json').read_text())
    changed=[r['path'] for r in baseline['tracked_files'] if sha(product/r['path'])!=r['sha256']]
    if changed or spec['product_commit']!=baseline['commit']:raise ValueError('Frozen source mismatch: '+str(changed))
    root.mkdir(parents=True);(root/'tmp').mkdir();os.environ['GEWU_DATA_ROOT']=str(root/'environment')
    (root/'runner_source.py').write_bytes(Path(__file__).read_bytes())
    save(root/'cases_spec.json',spec)
    os.environ['TMPDIR']=str(root/'tmp');tempfile.tempdir=str(root/'tmp');sys.dont_write_bytecode=True
    sys.path.insert(0,str(product));guard_writes(root)
    from paper_monitor import config, storage
    if storage.STORAGE_SCHEMA_VERSION!=spec['product_schema']:raise ValueError('Schema mismatch')
    rows=[]
    for case in spec['cases']:
        if a.families and case['family'] not in a.families:continue
        case_root=root/case['case_id'].removeprefix('V4-');case_root.mkdir();h=None
        row={'case_id':case['case_id'],'family':case['family'],'expected':case['expected'],'phase':'qualification','formal_result':False}
        try:
            h=Harness(case_root);save(case_root/'before.json',h.snapshot())
            observed=execute(h,case);row.update(observed=observed,passed=json.dumps(observed,sort_keys=True)==json.dumps(case['expected'],sort_keys=True),status='executed')
            snapshot=h.snapshot();save(case_root/'after.json',snapshot)
            if snapshot['foreign_key_errors']:row.update(passed=False,integrity_error='foreign_key_check')
        except Exception as exc:
            row.update(passed=False,status='runner_error',error=type(exc).__name__+': '+str(exc))
            (case_root/'exception.txt').write_text(traceback.format_exc())
        finally:
            if h:
                save(case_root/'operations.json',h.trace);h.close()
        save(case_root/'result.json',row);rows.append(row)
        print(json.dumps({'case_id':case['case_id'],'status':row['status'],'passed':row['passed']},ensure_ascii=False),flush=True)
    report={'phase':'qualification_before_design_lock','formal_result':False,'product_commit':baseline['commit'],
        'source_files_verified':len(baseline['tracked_files']),'source_changed':changed,'schema':storage.STORAGE_SCHEMA_VERSION,
        'runner_sha256':sha(root/'runner_source.py'),'case_spec_sha256':sha(root/'cases_spec.json'),'python':sys.version,
        'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'total':len(rows),
        'passed':sum(r['passed'] for r in rows),'runner_errors':sum(r['status']=='runner_error' for r in rows),
        'cases':rows,'production_data_accessed':False,'isolated_run_root':str(root),
        'coverage_limits':['Synthetic engineering qualification; not scientific semantic labels or formal results.',
            'Metadata-correction cases use documented provider-return fixture boundary.',
            'No real native UI or OS alias usability measured by this runner.']}
    save(root/'qualification.json',report)
    print(json.dumps({k:report[k] for k in ('phase','total','passed','runner_errors')},ensure_ascii=False))


if __name__=='__main__':main()
