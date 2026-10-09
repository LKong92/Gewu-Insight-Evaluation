"""Current-version multi-step engineering workflows; freshly generated fixtures.

The source-transport and failure-injection boundaries are recorded in each trace.
This module does not load product tests, old results or literature-store data.
"""
from contextlib import ExitStack
import hashlib
import http.client
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from run_b import Harness, canonical_identity, metadata_correction, save, sha


class Workflow(Harness):
    def __init__(self, root):
        super().__init__(root)
        self.steps=[];self.checks=[];self.previous='0'*64

    def workspace(self,path,query=None):
        self.serve()
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=20)
        conn.request('GET',path+('?' + urlencode(query) if query else ''),headers={'X-Gewu-Workspace':self.http.workspace_access.token})
        response=conn.getresponse();value=json.loads(response.read());conn.close()
        if response.status!=200:raise ValueError('Workspace observation failed: '+path+' '+str(response.status))
        return value

    def observe(self,name,result=None):
        snapshot=self.snapshot()
        for table in ('my_publications','aps_rss_feeds','aps_rss_entries','paper_identifiers','author_monitor_papers',
                      'ai_analyses','ai_write_requests','publication_import_jobs','publication_import_items','paper_metadata_refreshes'):
            if self.s.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                snapshot['tables'][table]=[dict(r) for r in self.s.conn.execute('SELECT * FROM '+table+' ORDER BY 1')]
        snapshot['tables']['metadata_job_settings']=[dict(r) for r in self.s.conn.execute("SELECT key,value FROM app_settings WHERE key LIKE 'metadata_job:%' OR key LIKE 'metadata_candidates:%' ORDER BY key")]
        api={'health':self.workspace('/api/health'),'library':self.workspace('/api/library'),'papers':{}}
        for p in snapshot['tables']['papers']:
            api['papers'][p['paper_id']]={'paper':self.workspace('/api/paper',{'paper_id':p['paper_id']}),
                'files':self.workspace('/api/paper-files',{'paper_id':p['paper_id']})}
        event={'step':name,'previous_event_sha256':self.previous,'state':snapshot,'api':api,'action_result':result}
        digest=hashlib.sha256(json.dumps(event,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
        save(self.root/'steps'/('%03d-%s.json'%(len(self.steps),name)),{**event,'event_sha256':digest})
        self.previous=digest;self.steps.append(name)
        self.check('foreign_keys:'+name,[],snapshot['foreign_key_errors'])
        return snapshot

    def step(self,name,fn):
        value=fn();self.observe(name,value);return value

    def check(self,name,expected,observed):
        self.checks.append({'invariant':name,'expected':expected,'observed':observed,
            'passed':json.dumps(expected,sort_keys=True,default=str)==json.dumps(observed,sort_keys=True,default=str)})

    def count(self,table):return self.s.conn.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def restart(self):
        before=self.snapshot()
        if self.http:
            self.http.shutdown();self.http.server_close();self.http_thread.join();self.http=None
        self.reopen()
        after=self.observe('restart_readback')
        for table in ('papers','resources','library_items','publication_notices','publication_notice_files','paper_aliases'):
            def stable(rows):
                return [{k:v for k,v in row.items() if k not in ('updated_at','last_seen_at','modified_at')} for row in rows]
            self.check('restart_persistence:'+table,stable(before['tables'][table]),stable(after['tables'][table]))


def rss(items):
    return ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">'+''.join(
        '<item><title>'+escape(title)+'</title><prism:doi>'+doi+'</prism:doi><prism:publicationDate>2026-09-29</prism:publicationDate><link>https://doi.org/'+doi+'</link></item>' for title,doi in items)+'</rdf:RDF>').encode()


def response(items=(),status=200):
    import requests
    r=requests.Response();r.status_code=status;r._content=rss(items);r.headers={'ETag':'v4-synthetic-etag','Last-Modified':'Tue, 29 Sep 2026 12:00:00 GMT'}
    return r


def sync_rss(w, items=None, *, status=200, force=True, slugs=None, error=None):
    from paper_monitor.sources import publisher
    with ExitStack() as stack:
        stack.enter_context(patch.object(publisher,'APS_RSS_REQUEST_INTERVAL_SECONDS',0))
        stack.enter_context(patch.object(publisher,'_APS_RSS_BLOCKED_UNTIL',0))
        transport=stack.enter_context(patch.object(publisher,'get_with_local_proxy_fallback',
            **({'side_effect':error} if error else {'return_value':response(items or [],status)})))
        result=publisher.sync_aps_rss_feeds(w.s,journal_slugs=slugs or ['pra'],force=force)
        calls=[{'args':list(c.args),'kwargs':c.kwargs} for c in transport.call_args_list]
    w.trace.append({'fixture_boundary':'RSS HTTP response bytes; real RSS parser and ingestion unchanged','requests':calls})
    return result,calls


def c14(w,v):
    regular=[('Synthetic quantum research alpha','10.1103/v4-alpha'),('Synthetic quantum research omega','10.1103/v4-omega')]
    notice=('Erratum: Synthetic quantum research','10.1103/v4-notice')
    if v<4:
        items=regular[:];items.insert(v-1,notice)
    else:items=[(title+': Synthetic quantum research','10.1103/v4-event-'+str(i)) for i,title in enumerate(('Correction','Retraction','Expression of concern','Withdrawal','Addendum'))]
    first,_=w.step('ingest_complete_rss',lambda:sync_rss(w,items))
    repeat,_=w.step('replay_same_rss',lambda:sync_rss(w,items))
    w.check('complete_status','success',first['status']);w.check('retry_status','success',repeat['status'])
    w.check('ordinary_paper_count',2 if v<4 else 0,w.count('papers'))
    w.check('retained_event_count',1 if v<4 else 5,w.count('publication_notices'))
    w.check('no_notice_rss_membership',2 if v<4 else 0,w.count('aps_rss_entries'))
    w.check('retry_no_new_identity',0,repeat['created'])


def c16(w,v):
    import requests
    items=[('Synthetic quantum first','10.1103/v4-first'),('Synthetic quantum broken','10.1103/v4-broken'),('Synthetic quantum last','10.1103/v4-last')]
    if v in (1,3):
        original=w.s.record_aps_rss_entries
        def fail_one(slug,entries,**kw):
            result=original(slug,entries,**kw)
            if entries[0]['doi']=='10.1103/v4-broken':raise sqlite3.IntegrityError('V4 injected membership failure')
            return result
        with patch.object(w.s,'record_aps_rss_entries',side_effect=fail_one):
            partial,_=w.step('entry_failure_with_continuation',lambda:sync_rss(w,items))
        w.check('partial_status','partial',partial['status']);w.check('successful_entries_kept',2,w.count('papers'))
        cached,calls=w.step('cached_partial_readback',lambda:sync_rss(w,items,force=False))
        w.check('cached_status_honest','partial',cached['status']);w.check('cache_no_fetch',0,len(calls))
        retried,calls=w.step('retry_requests_body',lambda:sync_rss(w,items))
        w.check('successful_retry','success',retried['status']);w.check('eventual_three_entries',3,w.count('papers'))
        w.check('no_conditional_header_after_partial',False,any(k in (calls[0]['kwargs'].get('headers') or {}) for k in ('If-None-Match','If-Modified-Since')))
        if v==3:
            failed,_=w.step('subsequent_transport_failure',lambda:sync_rss(w,error=requests.Timeout('V4 source timeout')))
            w.check('failed_cache_status','error',failed['status'])
            _,calls=w.step('retry_after_error',lambda:sync_rss(w,items))
            w.check('no_conditional_header_after_error',False,any(k in calls[0]['kwargs'].get('headers',{}) for k in ('If-None-Match','If-Modified-Since')))
    elif v==2:
        first,_=w.step('successful_response',lambda:sync_rss(w,items))
        cached,_=w.step('not_modified_response',lambda:sync_rss(w,status=304))
        w.check('initial_success','success',first['status']);w.check('valid_304','success',cached['status']);w.check('cache_retains_entries',3,w.count('aps_rss_entries'))
    else:
        result,_=w.step('first_feed_fails_second_continues',lambda:sync_rss(w,slugs=['pra','prb'],error=[requests.Timeout('V4 first feed'),response(items)]))
        w.check('aggregate_partial','partial',result['status']);w.check('first_error','error',result['feeds']['pra']['status'])
        w.check('second_success','success',result['feeds']['prb']['status']);w.check('second_items_kept',3,w.count('papers'))


def c17(w,v):
    from paper_monitor import paper_identity
    if v<4:
        variant={1:'same_doi',2:'concurrent',3:'late_doi'}[v]
        result=w.step('canonical_identity_transition',lambda:canonical_identity(w,{'variant':variant}))
        w.check('canonical_identity',True if v==3 else 1,result)
        pid=w.s.conn.execute('SELECT paper_id FROM papers').fetchone()[0]
        w.step('add_library_and_file',lambda:(w.s.add_library_item(paper_id=pid,folder_id=1),w.file(pid,attach=True)))
        token,_=w.token();key=w.s.get_paper(pid)['storage_key']
        status,_=w.step('canonical_http_read',lambda:w.http_call(token,'get_paper',{'gewu_key':key}))
        w.check('canonical_read',200,status)
    else:
        first=w.paper('first',doi='10.5555/v4-alias-owner');second=w.paper('second',doi=None)
        w.s.add_library_item(paper_id=first,folder_id=1);w.s.add_library_item(paper_id=second,folder_id=1)
        old=w.s.get_paper(second)['storage_key'];token,_=w.token(selection={'kind':'papers','keys':[old]})
        def merge():
            with paper_identity.transaction(w.s):paper_identity.merge(w.s,first,second,reason='v4_explicit_synthetic_evidence')
        w.step('verified_merge_with_alias',merge)
        status,_=w.step('read_through_old_key',lambda:w.http_call(token,'get_paper',{'gewu_key':old}))
        w.check('old_key_reads_same_work',200,status)
        outside=w.paper('outside',doi='10.5555/v4-outside')
        status,_=w.step('outside_key_stays_private',lambda:w.http_call(token,'get_paper',{'gewu_key':w.s.get_paper(outside)['storage_key']}))
        w.check('no_scope_expansion',404,status)


def c18(w,v):
    variant={1:'matched_refresh',2:'mismatched_refresh',3:'stale_refresh',4:'arxiv_edit'}[v]
    result=w.step('identifier_refresh_transition',lambda:metadata_correction(w,{'variant':variant,'clear_first':v==2}))
    w.check('correction_contract',True,result)
    token,_=w.token();key=w.s.get_paper('work')['storage_key']
    status,result=w.step('read_corrected_identity_via_http',lambda:w.http_call(token,'get_paper',{'gewu_key':key}))
    w.check('same_key_readable',200,status)
    if v==4:
        from paper_monitor import metadata_refresh
        w.paper('conflicting-owner',doi='10.5555/owned-doi')
        before=w.s.get_paper('work')
        def conflict():
            try:metadata_refresh.save_doi(w.s,'work','10.5555/owned-doi')
            except ValueError:return 'rejected'
            return 'accepted'
        w.check('new_identifier_collision_rejected','rejected',w.step('conflicting_identifier_edit',conflict))
        w.check('collision_preserves_record',before,w.s.get_paper('work'))


def import_args():
    return {'folder_id':1,'request_id':'v4-workflow-import-0001','metadata':{
        'title':'Synthetic workflow research','authors':['A. Researcher'],'journal':'Fixture Journal',
        'publication_type':'journal_article','publication_date':'2026-09-29','doi':'10.5555/v4-workflow-import',
        'arxiv_id':None,'abstract':'Synthetic fixture','source_url':'https://example.invalid/work'}}


def c21(w,v):
    args=import_args();token,_=w.token();old=None
    if v==2:
        pid=w.paper('monitor-cached',doi=args['metadata']['doi'],title=args['metadata']['title'],journal=args['metadata']['journal'],source='crossref')
        old=w.s.get_paper(pid)['storage_key'];w.observe('uncollected_monitor_identity')
    if v==4:
        bad={**args,'upload_id':'nonexistent-upload','file_type':'published_version'}
        s,r=w.step('invalid_supplied_upload',lambda:w.http_call(token,'import_paper',bad))
        w.check('invalid_upload_rejected',True,s>=400);w.check('no_metadata_only_fallback',0,w.count('papers'))
    s,first=w.step('metadata_only_import',lambda:w.http_call(token,'import_paper',args));w.check('metadata_import',200,s)
    key=first['gewu_key'];pid=w.s.paper_for_key(key)['paper_id']
    w.check('no_placeholder',0,len(w.resources(pid)))
    if old:w.check('monitor_key_retained',old,key)
    if v==3:
        s,again=w.step('exact_metadata_retry',lambda:w.http_call(token,'import_paper',args));w.check('retry_key',key,again.get('gewu_key'))
        changed={**args,'metadata':{**args['metadata'],'title':'Changed payload'}}
        s,r=w.step('changed_request_rejected',lambda:w.http_call(token,'import_paper',changed));w.check('conflict_status',409,s)
    upload=w.step('upload_real_synthetic_pdf',lambda:w.upload(token))
    later={**args,'request_id':'v4-workflow-import-0002','upload_id':upload,'file_type':'published_version'}
    s,file=w.step('attach_later_pdf',lambda:w.http_call(token,'import_paper',later))
    w.check('later_file_status',200,s);w.check('same_key_after_file',key,file.get('gewu_key'));w.check('one_file',1,len(w.resources(pid)))
    s,again=w.step('exact_file_retry',lambda:w.http_call(token,'import_paper',later))
    w.check('same_file_after_retry',file['file']['file_id'],again.get('file',{}).get('file_id'))


def c22(w,v):
    from paper_monitor import paper_identity
    pid=w.paper();item=w.s.add_library_item(paper_id=pid,folder_id=1);w.file(pid,attach=True)
    key=w.s.get_paper(pid)['storage_key']
    token,cid=w.token(scopes=['papers:read','files:read'],selection={'kind':'folder','folder_id':1})
    s,r=w.step('initial_authorized_read',lambda:w.http_call(token,'get_paper',{'gewu_key':key}));w.check('initial_read',200,s)
    if v==1:
        s,r=w.step('read_only_import_attempt',lambda:w.http_call(token,'import_paper',import_args()));w.check('write_denied',403,s)
        w.check('identity_unchanged',1,w.count('papers'))
    elif v==2:
        w.s.conn.execute("UPDATE ai_connections SET revoked_at='2026-10-01T00:00:00+00:00' WHERE id=?",(cid,));w.s.conn.commit()
        s,r=w.step('revoked_read',lambda:w.http_call(token,'get_paper',{'gewu_key':key}));w.check('revoke_enforced',401,s)
        second,cid2=w.token();w.s.conn.execute("UPDATE ai_connections SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(cid2,));w.s.conn.commit()
        s,r=w.step('expired_read',lambda:w.http_call(second,'get_paper',{'gewu_key':key}));w.check('expiry_enforced',401,s)
    elif v==3:
        private=w.s.create_library_root_folder(name='Private outside selection')
        w.step('move_membership_out_of_selection',lambda:w.s.move_library_item(item_id=item['id'],folder_id=private['id']))
        s,r=w.step('read_after_membership_move',lambda:w.http_call(token,'get_paper',{'gewu_key':key}));w.check('membership_rechecked',404,s)
    else:
        hidden=w.paper('hidden',doi='10.5555/hidden');hiddenkey=w.s.get_paper(hidden)['storage_key']
        path=w.resources(pid)[0]['stored_path'];w.s.create_paper_resource(paper_id=hidden,stored_path=path,file_type='preprint')
        w.step('old_alias_added',lambda:paper_identity.add_alias(w.s,'old-work-alias',pid));w.s.conn.commit()
        s,r=w.step('shared_file_does_not_grant_work',lambda:w.http_call(token,'get_paper',{'gewu_key':hiddenkey}));w.check('shared_path_not_authority',404,s)


def c24(w,v):
    from paper_monitor import ai_organize
    pid=w.paper();folder=w.s.create_library_folder(parent_id=1,name='Source subtree')
    item=w.s.add_library_item(paper_id=pid,folder_id=folder['id']);resource=w.file(pid,attach=True)
    key=w.s.get_paper(pid)['storage_key'];token,_=w.token();before=Path(w.s.get_paper_resource(resource['id'])['stored_path']).read_bytes()
    destination=w.s.create_library_folder(parent_id=1,name='Destination')
    if v==1:
        args={'source':{'gewu_key':key,'file_id':resource['id']},'name':'Renamed.pdf','request_id':'v4-rename-file-0001'}
        s,r=w.step('rename_file_via_mcp',lambda:w.http_call(token,'rename_file',args));w.check('rename_status',200,s)
        current=w.s.get_paper_resource(resource['id']);w.check('rename_filename','Renamed.pdf',Path(current['stored_path']).name)
        w.check('rename_preserves_bytes',hashlib.sha256(before).hexdigest(),sha(current['stored_path']))
    elif v==2:
        directory=w.ui.local_copy_dir_for_library_folder(w.s,folder['id']);(directory/'empty').mkdir();(directory/'extra.txt').write_text('unregistered synthetic user file')
        args={'folder_id':folder['id'],'parent_id':destination['id'],'request_id':'v4-move-folder-0001'}
        s,r=w.step('move_whole_subtree',lambda:w.http_call(token,'move_folder',args));w.check('move_status',200,s)
        target=w.ui.local_copy_dir_for_library_folder(w.s,folder['id'])
        w.check('empty_directory_preserved',True,(target/'empty').is_dir());w.check('unregistered_content_preserved','unregistered synthetic user file',(target/'extra.txt').read_text())
    elif v==3:
        private=w.s.create_library_root_folder(name='Unauthorized root')
        args={'source':{'membership_id':item['id']},'target':{'folder_id':private['id']},'request_id':'v4-denied-move-0001'}
        old=w.s.get_library_item(item['id'])
        s,r=w.step('attempt_unauthorized_move',lambda:w.http_call(token,'move_file',args));w.check('scope_boundary',403,s)
        w.check('membership_unchanged',old,w.s.get_library_item(item['id']))
    else:
        args={'source':{'membership_id':item['id']},'target':{'folder_id':destination['id']},'request_id':'v4-rollback-move-0001'}
        before_state=w.snapshot()
        with patch.object(ai_organize,'save_receipt',side_effect=OSError('V4 injected receipt failure')):
            s,r=w.step('receipt_failure_after_move',lambda:w.http_call(token,'move_file',args))
        w.check('failure_reported',True,s>=400)
        after=w.snapshot()
        for table in ('papers','resources','library_items'):w.check('rollback:'+table,before_state['tables'][table],after['tables'][table])
        s,r=w.step('retry_move_after_failure',lambda:w.http_call(token,'move_file',args));w.check('retry_success',200,s)
    current=w.s.get_paper_resource(resource['id']);w.check('original_resource_id_and_bytes',hashlib.sha256(before).hexdigest(),sha(current['stored_path']))


def c26(w,v):
    from paper_monitor import publication_jobs as jobs
    profile={'url':'https://scholar.google.com/citations?user=v4-synthetic','user_id':'v4-synthetic','name':'Synthetic Researcher'}
    job=w.step('create_publication_import',lambda:jobs.create_import(w.s,profile))
    def candidate(n):return {'paper':{'paper_id':'v4-scholar-'+str(n),'title':'Distinct synthetic research '+str(n),
        'journal':'Fixture Journal','publication_date':'2026','doi':'','source':'google-scholar'},
        'raw':{'authors':['Synthetic Researcher'],'google_scholar':{'publication_url':'https://scholar.google.com/citations?citation_for_view=v4-synthetic:'+str(n)}}}
    def page(ids,offset,finished=False):return {'candidates':[candidate(n) for n in ids],'next_offset':offset,'finished':finished}
    def current():return dict(w.s.conn.execute('SELECT * FROM publication_import_jobs WHERE id=?',(job['id'],)).fetchone())
    # Job-control boundary uses fixed provider page payloads. This tests job
    # persistence and selection, not live Scholar availability or parsing.
    w.trace.append({'fixture_boundary':'provider page payload for publication job control; ordinary add/merge/cursor storage unchanged'})
    with patch.object(jobs,'fetch_profile_page',return_value=page([1,2],100)):
        w.step('first_page_import',lambda:jobs.run_import_step(w.s))
    if v==1:
        w.step('pause_import',lambda:jobs.control_import(w.s,job['id'],'pause'))
        w.check('paused_status','paused',current()['status']);w.check('checkpoint_offset',100,current()['page_offset'])
        w.step('resume_import',lambda:jobs.control_import(w.s,job['id'],'resume'))
    elif v==2:
        w.restart();w.check('checkpoint_after_restart',100,current()['page_offset'])
    elif v==3:
        row=w.s.list_my_publications()[0];removed=row['paper_id']
        w.step('remove_publication',lambda:w.s.delete_my_publication(publication_id=row['id']))
    else:
        with patch.object(jobs,'fetch_profile_page',side_effect=RuntimeError('V4 source unavailable')):
            w.step('source_restriction',lambda:jobs.run_import_step(w.s))
        w.check('restricted_status','error',current()['status']);w.check('cursor_not_advanced',100,current()['page_offset'])
        w.step('resume_after_restriction',lambda:jobs.control_import(w.s,job['id'],'resume'))
    with patch.object(jobs,'fetch_profile_page',return_value=page([1,2,3],200,True)) as fetch:
        w.step('next_page_and_source_dedup',lambda:jobs.run_import_step(w.s))
        w.check('requested_saved_cursor',100,fetch.call_args.args[1])
    w.check('completed_status','complete',current()['status'])
    w.check('unique_saved_placements',2 if v==3 else 3,len(w.s.list_my_publications()))
    if v==3:w.check('tombstone_not_resurrected',False,removed in {r['paper_id'] for r in w.s.list_my_publications()})


from remaining_state_cases import c15,c19,c20,c23,c25
IMPLEMENTED={'C14':c14,'C15':c15,'C16':c16,'C17':c17,'C18':c18,'C19':c19,'C20':c20,'C21':c21,'C22':c22,'C23':c23,'C24':c24,'C25':c25,'C26':c26}
