"""New current-version workflows with explicit synthetic input boundaries."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch


def rejected(call):
    try:call()
    except (ValueError, OSError, RuntimeError) as exc:return {'rejected':True,'error':str(exc),'kind':type(exc).__name__}
    return {'rejected':False}


def text_pdf(title,doi='',extra=''):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    def literal(text):return text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    content='BT /F1 16 Tf 40 720 Td ('+literal(title)+') Tj /F1 10 Tf 0 -35 Td (DOI: '+literal(doi)+') Tj 0 -25 Td ('+literal(extra)+') Tj ET'
    stream=DecodedStreamObject();stream.set_data(content.encode('ascii'));page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_metadata({'/Title':title});out=io.BytesIO();writer.write(out);return out.getvalue()


def browser(w,title,doi):
    from paper_monitor.browser_capture import BrowserCaptureService
    service=BrowserCaptureService()
    capture=service.begin(w.path,{'url':'https://example.invalid/article/'+doi,'metadata':{'doi':doi,'title':title}})
    w.stack.callback(lambda: service.cancel(w.path,capture.token) if capture.token in service.captures else None)
    return service,capture


def c15(w,v):
    from paper_monitor import publication_notices as notices
    title='Author Correction: Synthetic quantum research';doi='10.5555/v4-notice'
    content=text_pdf(title,doi)
    if v==2:
        from paper_monitor.importers.inventory import import_library_inventory
        source=w.root/'source'/'notice.pdf';source.parent.mkdir();source.write_bytes(content)
        record={'path':str(source),'relative_path':'notice.pdf','parent_relative_path':'','filename':source.name,
            'extension':'.pdf','kind':'pdf','mime_type':'application/pdf','import_as':'paper_candidate',
            'size_bytes':len(content),'modified_at':'2026-09-29T00:00:00+08:00','doi':doi,'doi_source':'synthetic_inventory',
            'arxiv_id':None,'title':title,'authors':[],'page_count':1,'parse_status':'parsed','parse_error':None}
        inv=w.root/'inventory.json';inv.write_text(json.dumps({'summary':{'root':str(source.parent),'file_count':1},'directories':[],'files':[record]}))
        w.trace.append({'fixture_boundary':'fresh inventory metadata and real generated PDF; tests Loader relation handling, not inventory PDF extraction'})
        args=dict(storage=w.s,dry_run=False,preserve_folders=True,target_root=w.root/'copied')
        first=w.step('loader_retains_unresolved_notice',lambda:import_library_inventory(inv,**args))
        w.check('no_loader_errors',[],first['errors']);w.check('no_ordinary_work',0,w.count('papers'))
        w.check('relation_pending','needs_relation',first['publication_notices'][0]['status'])
        again=w.step('loader_replay',lambda:import_library_inventory(inv,**args))
        rows=[dict(r) for r in w.s.conn.execute('SELECT * FROM resources')]
        w.check('one_retained_file',1,len(rows));w.check('not_wrongly_owned',None,rows[0]['paper_id'])
        w.check('original_bytes',content.hex(),Path(rows[0]['stored_path']).read_bytes().hex())
        return
    pid=w.paper(title='Synthetic quantum research',doi='10.5555/v4-original');w.s.add_library_item(paper_id=pid,folder_id=1)
    original=w.file(pid,kind='published_version',attach=True);original_hash=hashlib.sha256(Path(original['stored_path']).read_bytes()).hexdigest()
    key=w.s.get_paper(pid)['storage_key']
    if v==1:
        service,capture=browser(w,title,doi)
        w.step('browser_receives_notice_pdf',lambda:service.upload(capture,content))
        w.step('browser_review_without_online_resolution',lambda:service.review(capture,w.s,{'resolve':False}))
        blocked=w.step('browser_blocks_missing_relation',lambda:rejected(lambda:service.save(capture,w.s,{'folder_id':1,'include_pdf':True})))
        w.check('missing_relation_rejected',True,blocked['rejected'])
        # Explicit reviewed relation is supplied as a provider-metadata fixture.
        # The product's notice routing, file handling and persistence run unchanged.
        capture.resolved['doi:'+doi]={'paper_id':'synthetic-notice','doi':doi,'title':title,
            'journal':'Fixture Journal','raw':{'crossref':{'update-to':[{'type':'correction','DOI':'10.5555/v4-original'}]}}}
        w.step('browser_reviews_verified_provider_relation',lambda:service.review(capture,w.s,{'resolve':False}))
        w.trace.append({'fixture_boundary':'explicit provider notice relation; no live online resolution'})
        result=w.step('browser_save_verified_relation',lambda:service.save(capture,w.s,{'folder_id':1,'include_pdf':True,'file_type':'published_version'}))
        w.check('existing_work_target',pid,result['paper_id'])
    else:
        from new_state_cases import import_args
        token,_=w.token();upload=w.upload(token,content=content)
        args=import_args();args.update(upload_id=upload,file_type='published_version',request_id='v4-notice-relation-0001')
        args['metadata'].update(title=title,doi=doi)
        relation={'kind':'correction_notice','related_dois':['10.5555/v4-original'],'evidence_url':'https://example.invalid/notice'}
        if v==4:
            other=w.paper('another',doi='10.5555/v4-another',title='Different independent work');w.s.add_library_item(paper_id=other,folder_id=1)
            for name,targets in [('unknown',['10.5555/nonexistent']),('multiple',['10.5555/v4-original','10.5555/v4-another']),('self',[doi])]:
                args['metadata']['publication_notice']={**relation,'related_dois':targets}
                status,result=w.step('reject_'+name+'_relation',lambda:w.http_call(token,'import_paper',args))
                w.check(name+'_status',409,status);w.check(name+'_no_attachment',1,len(w.resources(pid)))
        args['metadata']['publication_notice']=relation
        status,result=w.step('mcp_verified_notice_import',lambda:w.http_call(token,'import_paper',args))
        w.check('notice_import_status',200,status);w.check('same_work_key',key,result.get('gewu_key'))
        status,again=w.step('mcp_notice_exact_retry',lambda:w.http_call(token,'import_paper',args))
        w.check('notice_retry_id',result['file']['file_id'],again.get('file',{}).get('file_id'))
    rows=w.resources(pid)
    w.check('notice_is_separate_file',2,len(rows));w.check('notice_type_override',1,sum(r['file_type']=='correction_notice' for r in rows))
    w.check('notice_not_default',original['id'],w.s.resolve_default_paper_resource(pid)['id'])
    w.check('original_bytes_preserved',original_hash,hashlib.sha256(Path(w.s.get_paper_resource(original['id'])['stored_path']).read_bytes()).hexdigest())


def c19(w,v):
    from paper_monitor import metadata_jobs as jobs,metadata_refresh as refresh
    ids=['a-work','b-work','c-work'] if v<4 else ['a-work']
    scope=w.s.create_library_folder(parent_id=1,name='Refresh scope')['id']
    for pid in ids:
        w.paper(pid,title='Synthetic metadata research '+pid);w.s.add_library_item(paper_id=pid,folder_id=scope)
    resource=w.file(ids[0],kind='preprint',attach=True);w.s.set_preferred_paper_resource(ids[0],resource['id'])
    before=w.s.get_paper(ids[0]);data=Path(resource['stored_path']).read_bytes()
    def published(doi,**kw):
        pid=doi.removeprefix('10.5555/v4-')
        return {'paper_id':'remote-'+pid,'doi':doi,'title':'Synthetic metadata research '+pid,'journal':'Fixture Journal',
            'source':'crossref','url':'https://doi.org/'+doi,'publication_date':'2026-09-29','raw':{'DOI':doi,'authors':['A. Researcher']}}
    with ExitStack() as stack:
        # The new source is explicitly empty in this partial-refresh fixture.
        # Real source construction/parsing remains active, and no network is used.
        import requests
        from urllib.parse import urlsplit,parse_qs
        def empty_updates(adapter,request,**kwargs):
            parsed=urlsplit(request.url);query=parse_qs(parsed.query)
            assert parsed.hostname=='api.crossref.org' and parsed.path=='/works'
            assert query.get('filter')==['updates:'+w.s.get_paper(ids[0])['doi']] or all(x.startswith('updates:10.5555/v4-') for x in query.get('filter',[]))
            response=requests.Response();response.request=request;response.url=request.url;response.connection=adapter
            response.status_code=200;response.reason='OK';response.headers['Content-Type']='application/json';response.encoding='utf-8'
            response._content=b'{"message":{"items":[],"total-results":0}}';response._content_consumed=True;response.raw=io.BytesIO(response._content)
            w.trace.append({'fixture_boundary':'explicit empty Crossref updates wire response','request_url':request.url,'source_response':'no updates'})
            return response
        stack.enter_context(patch('requests.adapters.HTTPAdapter.send',empty_updates))
        core=w.ui.publication_metrics_metadata_from_doi
        stack.enter_context(patch.object(w.ui,'publication_metrics_metadata_from_doi',side_effect=core if v==4 else published))
        crossref=stack.enter_context(patch.object(w.ui,'publication_metadata_from_doi',side_effect=published))
        mocks={}
        for name,value in {'fetch_arxiv_by_id':None,'pubmed_metadata_from_doi':None,'ads_api_token':'',
            'semantic_scholar_request':SimpleNamespace(json=lambda:{}),'openalex_request':SimpleNamespace(json=lambda:{'results':[]})}.items():
            mocks[name]=stack.enter_context(patch.object(w.ui,name,return_value=value))
        w.trace.append({'fixture_boundary':'metadata provider payloads; real metadata refresh, queue, checkpoints and scope recheck'})
        if v<4:
            job=w.step('create_metadata_job',lambda:jobs.create(w.s,folder_id=scope,mode='full',skip_days=0))
            def pause(current):
                if current['current']==1:jobs.control(w.s,job['job_id'],'pause')
            w.step('run_and_pause_after_first',lambda:jobs.run_job(w.s,job['job_id'],progress=pause))
            checkpoint=jobs.get(w.s,job['job_id']);w.check('paused','paused',checkpoint['status']);w.check('checkpoint',1,checkpoint['current'])
            if v==2:
                checkpoint['status']='running';jobs._save(w.s,checkpoint)
                jobs._INITIALIZED.discard(str(w.path.resolve()));w.restart()
                recovered=w.step('reinitialize_interrupted_job',lambda:jobs.get(w.s,job['job_id']))
                w.check('interrupted_job_paused','paused',recovered['status']);w.check('checkpoint_retained',1,recovered['current'])
                w.trace.append({'restart_boundary':'Storage and HTTP service restarted, metadata module initialization reset; process-kill recovery not measured'})
            if v==3:
                outside=w.s.create_library_root_folder(name='Outside refresh scope')
                item=w.s.conn.execute('SELECT id FROM library_items WHERE paper_id=?',('b-work',)).fetchone()[0]
                w.step('move_remaining_item_outside_scope',lambda:w.s.move_library_item(item_id=item,folder_id=outside['id']))
            w.step('resume_metadata_job',lambda:jobs.control(w.s,job['job_id'],'resume'))
            w.step('finish_remaining_metadata',lambda:jobs.run_job(w.s,job['job_id']))
            done=jobs.get(w.s,job['job_id']);w.check('completed','completed',done['status']);w.check('no_lost_position',3,done['current'])
            w.check('scope_removed_count',1 if v==3 else 0,done['counts']['removed'])
        else:
            pid=ids[0]
            mocks['openalex_request'].side_effect=RuntimeError('V4 injected partial source failure')
            w.step('quick_refresh',lambda:refresh.refresh(w.s,pid,mode='quick'))
            w.check('quick_does_not_satisfy_full',False,refresh.recently_completed(w.s,pid,'full'))
            partial=w.step('full_with_one_source_failure',lambda:refresh.refresh(w.s,pid,mode='full',skip_days=3))
            w.check('partial_status','partial',partial['metadata_refresh']['status']);crossref_calls=crossref.call_count;openalex_calls=mocks['openalex_request'].call_count
            mocks['openalex_request'].side_effect=None
            retry=w.step('retry_only_incomplete_sources',lambda:refresh.refresh(w.s,pid,mode='full',skip_days=3))
            w.check('crossref_not_repeated',crossref_calls,crossref.call_count)
            w.check('failed_source_retried',openalex_calls+1,mocks['openalex_request'].call_count)
            w.check('full_now_satisfies_quick',True,refresh.recently_completed(w.s,pid,'quick'))
            skipped=w.step('quick_batch_skips_completed_full',lambda:refresh.refresh(w.s,pid,mode='quick',origin='batch',skip_days=3))
            w.check('skip_completed','skipped_recent',skipped['metadata_refresh']['status'])
    after=w.s.get_paper(ids[0])
    for field in ('storage_key','preferred_resource_id','preferred_resource_manual'):w.check('file_preservation:'+field,before[field],after[field])
    w.check('pdf_bytes_preserved',data.hex(),Path(w.s.get_paper_resource(resource['id'])['stored_path']).read_bytes().hex())


def c20(w,v):
    from paper_monitor import metadata_refresh
    title='Synthetic browser quantum research';doi='10.5555/v4-browser'
    pid=w.paper(doi=doi,title=title);key=w.s.get_paper(pid)['storage_key']
    service,capture=browser(w,title,doi)
    content=text_pdf(title,doi)
    w.step('browser_receives_pdf',lambda:service.upload(capture,content))
    review=w.step('browser_review',lambda:service.review(capture,w.s,{'resolve':False}))
    w.check('review_resolves_existing_key',key,review['paper']['gewu_key'])
    if v==2:
        before=w.snapshot();w.step('cancel_without_save',lambda:service.cancel(w.path,capture.token))
        after=w.snapshot()
        for table in ('papers','resources','library_items'):w.check('cancel_preserves:'+table,before['tables'][table],after['tables'][table])
        w.check('cancel_removes_capture_file',False,capture.path.exists());return
    if v==3:
        w.step('edit_identifier_while_review_open',lambda:metadata_refresh.save_doi(w.s,pid,'10.5555/v4-edited'))
        result=w.step('reject_stale_review',lambda:rejected(lambda:service.save(capture,w.s,{'folder_id':1,'include_pdf':True})))
        w.check('stale_save_rejected',True,result['rejected']);w.check('no_file_from_stale_review',0,len(w.resources(pid)));return
    if v==4:
        w.step('replace_pdf_after_review',lambda:service.upload(capture,text_pdf('Different independent research','10.5555/v4-other')))
        result=w.step('reject_save_without_new_review',lambda:rejected(lambda:service.save(capture,w.s,{'folder_id':1,'include_pdf':True})))
        w.check('fresh_review_required',True,result['rejected'])
        review=w.step('review_mismatched_pdf',lambda:service.review(capture,w.s,{'resolve':False}))
        w.check('conflicting_identifiers_block_save',False,review['can_save']);w.check('no_conflicting_file',0,len(w.resources(pid)));return
    first=w.step('save_existing_article_pdf',lambda:service.save(capture,w.s,{'folder_id':1,'include_pdf':True,'file_type':'preprint'}))
    w.check('saved',True,first['pdf_saved']);rid=w.resources(pid)[0]['id'];w.s.set_preferred_paper_resource(pid,rid)
    service2,repeat=browser(w,title,doi);service2.upload(repeat,content);service2.review(repeat,w.s,{'resolve':False})
    reused=w.step('repeat_capture_same_bytes',lambda:service2.save(repeat,w.s,{'folder_id':1,'include_pdf':True,'file_type':'published_version'}))
    w.check('exact_duplicate_reused',True,reused['duplicate_file']);w.check('one_file',1,len(w.resources(pid)))
    w.check('manual_default_retained',rid,w.s.resolve_default_paper_resource(pid)['id']);w.check('key_retained',key,w.s.get_paper(pid)['storage_key'])


def c23(w,v):
    from paper_monitor import mcp_server
    pid=w.paper();w.s.add_library_item(paper_id=pid,folder_id=1);source=w.file(pid,kind='published_version',attach=True)
    original=Path(source['stored_path']).read_bytes();key=w.s.get_paper(pid)['storage_key']
    token,_=w.token(scopes=['papers:read','files:read','analysis:write']);w.serve()
    def client():
        c=mcp_server.GewuClient('http://127.0.0.1:'+str(w.http.server_port),token);w.stack.callback(c.close);return c
    c=client();delivery=w.step('authorized_client_file_delivery',lambda:c.get_paper_file({'gewu_key':key}))
    local=Path(delivery['delivery']['local_path'])
    w.check('delivered_bytes',original.hex(),local.read_bytes().hex());w.check('read_only_copy',0,local.stat().st_mode&0o222)
    args={'gewu_key':key,'markdown':'# Synthetic evaluation analysis\n\nA synthetic analysis for testing append-only saving.',
        'request_id':'v4-analysis-save-0001','source_file_id':source['id'],'source_sha256':delivery['sha256']}
    if v==3:
        current=Path(w.s.get_paper_resource(source['id'])['stored_path']);current.write_bytes(w.pdf(tag='new-source-version'))
        status,result=w.step('reject_analysis_for_changed_source',lambda:w.http_call(token,'save_analysis',args))
        w.check('stale_source_rejected',409,status);w.check('no_stale_analysis',1,len(w.resources(pid)))
        w.check('delivered_copy_stays_original',original.hex(),local.read_bytes().hex());return
    status,first=w.step('append_first_analysis',lambda:w.http_call(token,'save_analysis',args));w.check('analysis_saved',200,status)
    rid=first['file']['file_id'];note_path=Path(w.s.get_paper_resource(rid)['stored_path']);note_bytes=note_path.read_bytes()
    if v==1:
        c.close();w.restart();c=client()
        note=w.step('read_analysis_in_new_client_session',lambda:c.request('read_paper',{'gewu_key':key,'file_id':rid}))
        w.check('new_session_reads_analysis',True,args['markdown'] in note['text'])
    elif v==2:
        status,again=w.step('retry_same_analysis_request',lambda:w.http_call(token,'save_analysis',args))
        w.check('same_analysis_id',rid,again.get('file',{}).get('file_id'));w.check('only_one_analysis',2,len(w.resources(pid)))
        status,conflict=w.step('reject_changed_content_same_request',lambda:w.http_call(token,'save_analysis',{**args,'markdown':'Changed analysis'}))
        w.check('changed_request_conflict',409,status)
    else:
        with patch.object(mcp_server,'MAX_DELIVERY_FILES',1):
            blocked=w.step('delivery_quota_blocks_second_file',lambda:rejected(lambda:c.get_paper_file({'gewu_key':key,'file_id':rid})))
            w.check('quota_enforced',True,blocked['rejected'])
            released=w.step('release_client_copy',lambda:c.release_paper_file({'delivery_id':delivery['delivery']['delivery_id']}))
            w.check('release_frees_slot',0,released['quota']['used_files'])
            note=w.step('deliver_analysis_after_release',lambda:c.get_paper_file({'gewu_key':key,'file_id':rid}))
            w.check('analysis_delivery_bytes',note_bytes.hex(),Path(note['delivery']['local_path']).read_bytes().hex())
        status,second=w.step('append_distinct_second_analysis',lambda:w.http_call(token,'save_analysis',{**args,'request_id':'v4-analysis-save-0002','markdown':'Second separate synthetic analysis'}))
        w.check('new_analysis_gets_new_id',True,second.get('file',{}).get('file_id')!=rid)
        status,r=w.step('old_analysis_not_overwritten',lambda:w.http_call(token,'save_analysis',{**args,'markdown':'Attempted overwrite'}));w.check('overwrite_rejected',409,status)
    w.check('prior_analysis_bytes_preserved',note_bytes.hex(),note_path.read_bytes().hex())
    w.check('original_pdf_bytes_preserved',original.hex(),Path(w.s.get_paper_resource(source['id'])['stored_path']).read_bytes().hex())
    w.check('analysis_does_not_change_default',source['id'],w.s.resolve_default_paper_resource(pid)['id'])


def c25(w,v):
    from paper_monitor import finder_alias as aliases,file_layout,file_reassignment,file_layout_journal
    if v in (1,2):
        pid=w.paper();key=w.s.get_paper(pid)['storage_key'];folders=[w.s.create_library_folder(parent_id=1,name='First folder'),w.s.create_library_root_folder(name='Second root')]
        paths=[];resources=[];contents=[]
        for index,folder in enumerate(folders):
            item=w.s.add_library_item(paper_id=pid,folder_id=folder['id']);w.s.rename_library_item(item_id=item['id'],name='Work-'+str(index)+'.pdf')
            path=w.ui.local_copy_dir_for_library_folder(w.s,folder['id'])/('Work-'+str(index)+'.pdf');path.parent.mkdir(parents=True,exist_ok=True)
            content=w.pdf(tag='different-version-'+str(index));path.write_bytes(content)
            row=w.s.create_paper_resource(paper_id=pid,stored_path=str(path),file_type='unknown',added_via='legacy_backfill')
            paths.append(path);resources.append(row);contents.append(content)
        w.s.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=?,primary_resource_id=? WHERE paper_id=?',(str(paths[1]),str(paths[1]),resources[1]['id'],pid));w.s.conn.commit()
        w.step('reconcile_multiple_roots',lambda:file_layout.reconcile(w.s,pid))
        w.check('first_projection_is_alias',True,aliases.is_alias(paths[0]));w.check('alias_target',str(paths[1]),str(aliases.resolve(paths[0])))
        if v==2:
            w.check('native_finder_flag',True,bool(int.from_bytes(aliases.get_attribute(paths[0],'com.apple.FinderInfo')[8:10],'big')&0x8000))
            w.check('native_not_symlink',False,paths[0].is_symlink())
            renamed=paths[1].with_name('Finder renamed.pdf');paths[1].rename(renamed)
            w.check('bookmark_tracks_rename',str(renamed),str(aliases.resolve(paths[0])))
            w.step('repair_registered_path_after_rename',lambda:w.ui.update_paper_pdf_paths(w.s,pid,renamed,message='synthetic external rename'))
            w.step('resynchronize_native_aliases',lambda:w.ui.sync_all_pdf_aliases_for_paper(w.s,pid,old_target=paths[1],preserve_canonical_name=True))
        for row,content in zip(resources,contents):
            current=w.s.get_paper_resource(row['id']);w.check('resource_bytes:'+str(row['id']),content.hex(),Path(current['stored_path']).read_bytes().hex())
            copies=[p for p in w.root.rglob('*.pdf') if p.is_file() and not aliases.is_alias(p) and p.read_bytes()==content]
            w.check('one_physical_copy:'+str(row['id']),1,len(copies))
        w.check('same_key',key,w.s.get_paper(pid)['storage_key']);return
    pid=w.paper();w.s.add_library_item(paper_id=pid,folder_id=1);main=w.file(pid,kind='published_version',attach=True)
    if v==3:
        other=w.paper('external-owner',title='External synthetic document')
        # The product treats the SQLite parent as managed legacy storage.
        # Put the external fixture outside that directory, inside the isolated run.
        external=w.root.parent/'external-inputs'/w.root.name/'external-origin.rtf'
        external.parent.mkdir(parents=True);external.write_bytes(b'{\\rtf1 external original}')
        resource=w.s.create_paper_resource(paper_id=other,stored_path=str(external),storage_mode='linked',file_type='analysis')
        w.step('move_linked_file_ownership',lambda:file_reassignment.reassign_paper_file(w.s,other,resource['id'],target_key=w.s.get_paper(pid)['storage_key']))
        current=w.s.get_paper_resource(resource['id']);w.check('external_original_preserved',b'{\\rtf1 external original}'.hex(),external.read_bytes().hex())
        w.check('owned_copy_matches',external.read_bytes().hex(),Path(current['stored_path']).read_bytes().hex())
        w.check('new_owner',pid,current['paper_id']);return
    attachment=w.ui.attach_file_to_paper(w.s,paper_id=pid,filename='note.md',content=b'Synthetic original note',file_type='analysis')
    path=Path(attachment['stored_path']);before=w.snapshot()
    with patch.object(w.ui,'move_path_to_macos_trash',side_effect=OSError('V4 injected Trash failure')):
        failure=w.step('trash_failure',lambda:rejected(lambda:w.ui.delete_paper_resource(w.s,pid,attachment['id'])))
    w.check('trash_failure_reported',True,failure['rejected']);w.check('trash_failure_preserves_bytes',b'Synthetic original note'.hex(),path.read_bytes().hex())
    w.check('trash_failure_preserves_rows',before['tables']['resources'],w.snapshot()['tables']['resources'])
    # Leave a genuine interrupted move journal before recreating storage/service.
    destination=path.with_name('interrupted-note.md');journal=file_layout_journal.MoveJournal(w.s,pid)
    w.step('journaled_move_before_database_commit',lambda:journal.move(path,destination,attachment['id']))
    w.check('interrupted_source_absent',False,path.exists());w.restart()
    w.step('recover_interrupted_move',lambda:file_layout_journal.recover(w.s))
    w.check('recovery_restores_registered_bytes',b'Synthetic original note'.hex(),path.read_bytes().hex());w.check('recovery_removes_uncommitted_destination',False,destination.exists())
    def trash(source):
        target=w.root/'isolated_trash'/source.name;target.parent.mkdir(exist_ok=True);shutil.move(str(source),str(target));return target
    with patch.object(w.ui,'move_path_to_macos_trash',side_effect=trash):
        result=w.step('retry_delete_after_recovery',lambda:w.ui.delete_paper_resource(w.s,pid,attachment['id']))
    w.check('retry_deleted_resource',None,w.s.get_paper_resource(attachment['id']));w.check('default_preserved',main['id'],w.s.resolve_default_paper_resource(pid)['id'])
    w.trace.append({'fixture_boundary':'injected Trash failure then isolated synthetic Trash sink; original macOS Trash untouched'})
