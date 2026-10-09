#!/usr/bin/env python3
"""Collect and replay native discovery into a fresh isolated product workspace.

Journal uses its normal range engine plus authenticated daily UI responses;
Subject uses the actual range-search HTTP handler; Author uses the normal initial
refresh entry and authenticated cards. No source parser/filter/storage overrides.
Synthetic HTTP responses are allowed only in explicit qualification mode.
"""
import argparse
from contextlib import ExitStack
import datetime as dt
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from urllib.parse import urlencode
from unittest.mock import patch


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        f.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def acquisition_design(archive, design_stage='DESIGN'):
    if design_stage == 'A_DESIGN':
        from a_design import verify
        return verify(archive)
    if design_stage != 'DESIGN':
        raise ValueError('Unknown acquisition design stage')
    from stage_control import verify_stage
    stage = verify_stage(archive, 'DESIGN')
    if stage['details'].get('mode') != 'formal':
        raise ValueError('Qualification design cannot authorize formal acquisition')
    return stage


def require_locked_input(archive, path, design_stage='DESIGN'):
    stage = acquisition_design(archive, design_stage)
    name = str(path.resolve().relative_to(archive.resolve()))
    if not any(r['path'] == name and r['sha256'] == sha(path) for r in stage['files']):
        raise ValueError('Formal collector input is not included in acquisition design: ' + name)


class NativeCollector:
    def __init__(self, product, root, config, axis, bindings):
        from run_b import Harness
        self.h = Harness(root / 'workspace')
        self.product, self.root, self.config, self.axis, self.bindings = product, root, config, axis, bindings
        self.occurrences, self.responses, self.date_exclusions = [], [], []

    def call_ui(self, method, path, payload=None):
        self.h.serve()
        conn = http.client.HTTPConnection('127.0.0.1', self.h.http.server_port, timeout=172800)
        conn.request(method, path, json.dumps(payload) if payload is not None else None,
            {'X-Gewu-Workspace': self.h.http.workspace_access.token, 'Content-Type': 'application/json'})
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        locator = 'ui/%04d.json' % (len(self.responses) + 1)
        raw_locator = locator[:-5] + '.body'
        (self.root / 'ui').mkdir(exist_ok=True)
        with (self.root / raw_locator).open('xb') as f:
            f.write(raw)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            write(self.root / locator, {'method': method, 'path': path, 'payload': payload,
                'status': response.status, 'response': None, 'parse_error': str(exc),
                'raw_body_path': raw_locator, 'raw_body_sha256': sha(self.root / raw_locator)})
            self.responses.append({'path': locator, 'sha256': sha(self.root / locator),
                'status': response.status, 'parse_failed': True})
            raise RuntimeError('Native UI returned invalid JSON: %s %s HTTP %s' % (method, path, response.status)) from exc
        write(self.root / locator, {'method': method, 'path': path, 'payload': payload,
            'status': response.status, 'response': value,
            'raw_body_path': raw_locator, 'raw_body_sha256': sha(self.root / raw_locator)})
        self.responses.append({'path': locator, 'sha256': sha(self.root / locator), 'status': response.status})
        if response.status != 200:
            raise RuntimeError('Native UI request failed: %s %s HTTP %s' % (method, path, response.status))
        return value, locator

    def add_cards(self, payload, locator, monitor=None):
        from discovery_frames import author_window_includes
        start, end = self.config['windows'][self.axis]
        for order, card in enumerate(payload.get('papers', [])):
            if self.axis == 'author' and not author_window_includes(card, start, end):
                self.date_exclusions.append({'response_path': locator, 'display_order': order,
                    'reason': 'study_window_on_displayed_date_not_a_native_Author_UI_filter'})
                continue
            if self.axis == 'journal':
                monitors = [card.get('journal')]
            elif self.axis == 'subject':
                monitors = [r['key'] for r in card.get('theme_groups', [])]
            else:
                monitors = [monitor]
            for key in monitors:
                row = {'occurrence_id': '%s-%06d' % (self.axis, len(self.occurrences) + 1),
                    'axis': self.axis, 'monitor_id': key, 'response_path': locator,
                    'display_order': order, 'card': card}
                self.occurrences.append(row)

    def run(self):
        h, ui = self.h, self.h.ui
        start, end = [dt.date.fromisoformat(s) for s in self.config['windows'][self.axis]]
        if self.axis == 'journal':
            from paper_monitor.config import load_config
            from paper_monitor.monitor import run_journal_monitor
            native_config = load_config(self.product / 'config/journals.json', db_path=h.path)
            write(self.root / 'native_journal_configuration.json', {
                'journals': [vars(j) for j in native_config.journals],
                'section_policies': native_config.section_policies,
                'keep_unknown_sections': native_config.keep_unknown_sections})
            result = run_journal_monitor(config=native_config, storage=h.s, start_date=start, end_date=end,
                enrich=True, progress_callback=lambda name, done, total: print(json.dumps({
                    'axis': 'journal', 'completed_monitor': name, 'done': done, 'total': total}), flush=True))
            write(self.root / 'native_summary.json', result)
            for i in range((end - start).days + 1):
                day = (start + dt.timedelta(days=i)).isoformat()
                payload, locator = self.call_ui('GET', '/api/report?' + urlencode({'date': day, 'auto_fetch': 0}))
                self.add_cards(payload, locator)
        elif self.axis == 'subject':
            ui.save_custom_theme_groups(h.s, [dict(row, is_custom=True) for row in self.config['subjects']])
            groups = ui.load_theme_groups(h.s)
            keys = [ui.clean_theme_group_key(r['key']) for r in self.config['subjects']]
            if len(set(keys)) != len(keys) or not set(keys).issubset(groups):
                raise ValueError('Configured subjects were not registered under their native normalized keys')
            query_plan, query_groups = ui.theme_network_query_plan(groups, keys)
            write(self.root / 'native_subject_query_plan.json', {'queries': query_plan,
                'query_groups': {k: sorted(v) for k, v in query_groups.items()},
                'all_registered_groups': groups, 'requested_group_keys': keys,
                'network_queries_per_group': ui.THEME_NETWORK_QUERIES_PER_GROUP,
                'network_queries_per_source_run': ui.THEME_NETWORK_QUERIES_PER_SOURCE_RUN})
            payload, locator = self.call_ui('POST', '/api/theme-search', {
                'from_date': start.isoformat(), 'until_date': end.isoformat(), 'group': ','.join(keys)})
            self.add_cards(payload, locator)
            write(self.root / 'native_summary.json', payload['summary'])
        else:
            summaries = []
            for binding in self.bindings['authors']:
                if binding.get('verified') is not True:
                    raise ValueError('Unverified author provider binding: ' + binding['author_id'])
                profile = ui.sanitize_author_monitor_profile(binding['profile'])
                if not profile:
                    raise ValueError('Native product rejected the author profile')
                monitor = h.s.add_author_monitor(profile)
                result = ui.refresh_author_monitor_for_db(h.path, monitor['id'], initial=True, force=True)
                summaries.append({'roster_author_id': binding['author_id'], 'native_monitor_id': monitor['id'], 'result': result})
                payload, locator = self.call_ui('GET', '/api/author-monitor?' + urlencode({
                    'author_id': monitor['id'], 'cards_only': 1}))
                self.add_cards(payload, locator, binding['author_id'])
                print(json.dumps({'axis': 'author', 'author_id': binding['author_id'],
                    'status': result.get('status'), 'visible_cards': len(payload.get('papers', []))}), flush=True)
            write(self.root / 'native_summary.json', summaries)
    def persist_observations(self):
        """Retain partial evidence even when a native request or parser fails."""
        h = self.h
        write(self.root / 'occurrences.json', self.occurrences)
        write(self.root / 'ui_manifest.json', self.responses)
        write(self.root / 'study_window_exclusions.json', self.date_exclusions)
        # Candidate membership comes only from UI responses above. SQLite is
        # archived independently as trace evidence, never a replacement frame.
        tables = {}
        for name in ('fetch_runs','papers','theme_results','journal_monitor_papers',
                     'author_monitors','author_monitor_papers','publication_notices'):
            exists = h.s.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if exists:
                tables[name] = [dict(r) for r in h.s.conn.execute('SELECT * FROM ' + name)]
        write(self.root / 'native_storage_trace.json', tables)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--product-root', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--axis', choices=['journal','subject','author'], required=True)
    p.add_argument('--mode', choices=['qualification','qualification-replay','record','replay'], required=True)
    p.add_argument('--source-archive')
    p.add_argument('--design-stage', choices=['DESIGN','A_DESIGN'], default='DESIGN')
    p.add_argument('--author-bindings')
    args = p.parse_args()
    qualification = args.mode.startswith('qualification')
    replaying = args.mode.endswith('replay')
    product, root = Path(args.product_root).resolve(), Path(args.output).resolve()
    archive = product / 'benchmarks/evaluation'
    if product == Path(os.environ.get('GEWU_FORBIDDEN_PRODUCTION_ROOT', '/__forbidden_production__')):
        raise ValueError('Never run against the original product workspace')
    baseline = json.loads((archive / 'control/baseline.json').read_text())
    if any(sha(product / r['path']) != r['sha256'] for r in baseline['tracked_files']):
        raise ValueError('Frozen product source changed')
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    bindings = json.loads(Path(args.author_bindings).read_text()) if args.author_bindings else {}
    deadline_epoch = None
    if not qualification:
        require_locked_input(archive, config_path, args.design_stage)
        from a_design import safe
        policy_path = safe(archive, config['source_limits_manifest'])
        require_locked_input(archive, policy_path, args.design_stage)
        policy = json.loads(policy_path.read_text())
        if policy.get('product_commit') != baseline['commit'] or policy.get('native_limits_unchanged') is not True:
            raise ValueError('Formal source policy differs from the frozen product')
        if any(sha(product / r['path']) != r['sha256'] for r in policy['source_code']):
            raise ValueError('Native source policy code hashes do not match')
        for name in ('run_a.py','source_transport.py','discovery_frames.py','discovery_guard.py','run_b.py'):
            require_locked_input(archive, Path(__file__).resolve().parent / name, args.design_stage)
        if args.axis == 'author':
            require_locked_input(archive, Path(args.author_bindings), args.design_stage)
            if len(bindings.get('authors', [])) != 24:
                raise ValueError('Formal author coverage must retain the 24 fixed authors')
        if len(config['subjects']) != 8:
            raise ValueError('Formal subject configuration changed')
        if config.get('collection_deadline_hours') != 48:
            raise ValueError('Approved collection deadline must remain 48 hours')
        if args.mode == 'record':
            clock_path = archive / 'control/formal/COLLECTION_CLOCK.json'
            if not clock_path.exists():
                stamp = dt.datetime.now(dt.timezone.utc)
                try:
                    write(clock_path, {'started_at': stamp.isoformat(),
                        'deadline_epoch': stamp.timestamp() + 48 * 3600,
                        'design_stage': args.design_stage,
                        'design_sha256': sha(archive / ('control/formal/' + args.design_stage + '.json'))})
                except FileExistsError:
                    pass
            clock = json.loads(clock_path.read_text())
            if clock.get('design_stage', 'DESIGN') != args.design_stage or clock['design_sha256'] != sha(archive / ('control/formal/' + args.design_stage + '.json')):
                raise ValueError('Acquisition clock belongs to a different design')
            deadline_epoch = clock['deadline_epoch']
            if dt.datetime.now(dt.timezone.utc).timestamp() >= deadline_epoch:
                raise ValueError('The shared 48-hour collection window has ended')
    if args.axis == 'author' and not bindings:
        raise ValueError('Author acquisition needs explicit verified provider bindings')
    if replaying and not args.source_archive:
        raise ValueError('Offline replay needs the original transport archive')
    if replaying:
        original_root = Path(args.source_archive).resolve().parent
        original = json.loads((original_root / 'acquisition.json').read_text())
        expected_phase = 'qualification' if qualification else 'record'
        if original.get('phase') != expected_phase or original.get('axis') != args.axis or not original.get('complete'):
            raise ValueError('Replay must match a completed acquisition of the same axis and study phase')
        if original.get('product_commit') != baseline['commit'] or json.loads((original_root / 'input_configuration.json').read_text()) != config:
            raise ValueError('Replay product/configuration differs from the original acquisition')
        if args.axis == 'author' and json.loads((original_root / 'author_bindings.json').read_text()) != bindings:
            raise ValueError('Replay author identities differ from acquisition')
    root.mkdir(parents=True, exist_ok=False)
    (root / 'tmp').mkdir()
    (root / 'workspace').mkdir()
    write(root / 'input_configuration.json', config)
    if bindings: write(root / 'author_bindings.json', bindings)
    names = ['run_a.py','a_design.py','source_transport.py','discovery_frames.py','discovery_guard.py','run_b.py']
    if qualification and not replaying: names.append('discovery_fixture.py')
    for name in names:
        (root / name).write_bytes((Path(__file__).resolve().parent / name).read_bytes())
    os.environ['GEWU_DATA_ROOT'] = str(root / 'environment')
    os.environ['TMPDIR'] = str(root / 'tmp')
    tempfile.tempdir = str(root / 'tmp')
    for key in ('OPENALEX_API_KEY','OPENALEX_MAILTO','CROSSREF_MAILTO','SEMANTIC_SCHOLAR_API_KEY','NCBI_API_KEY'):
        os.environ.pop(key, None)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(product))
    from discovery_guard import guard_discovery
    from source_transport import SourceTransport
    guard_discovery(root, allow_live=args.mode == 'record')
    collector, report = None, {'phase': args.mode, 'axis': args.axis, 'complete': False,
        'product_commit': baseline['commit'], 'source_files_verified': len(baseline['tracked_files']),
        'collector_sha256': {n: sha(root / n) for n in names},
        'formal_scores': False, 'original_app_data_used': False,
        'design_stage': args.design_stage if not qualification else None,
        'design_sha256': sha(archive / ('control/formal/' + args.design_stage + '.json')) if not qualification else None,
        'entry_boundary': 'native backend/range HTTP and authenticated UI readback; no mouse/keyboard claim'}
    try:
        with ExitStack() as stack:
            # Anonymous configuration never reads the user's .netrc credentials.
            stack.enter_context(patch('requests.sessions.get_netrc_auth', return_value=None))
            if qualification and not replaying:
                from discovery_fixture import adapter_response
                stack.enter_context(patch('requests.adapters.HTTPAdapter.send', adapter_response))
            transport = stack.enter_context(SourceTransport(
                Path(args.source_archive).resolve() if replaying else root / 'sources',
                'replay' if replaying else 'record', deadline_epoch=deadline_epoch))
            collector = NativeCollector(product, root, config, args.axis, bindings)
            collector.run()
            if qualification:
                if len(collector.occurrences) != 1:
                    raise AssertionError('Synthetic qualification must surface exactly its one seeded candidate')
                report['qualification_expected_candidate_observed'] = True
            if replaying:
                report['replay'] = transport.assert_consumed()
            report.update(complete=True, observed_occurrences=len(collector.occurrences),
                ui_responses=len(collector.responses), date_exclusions=len(collector.date_exclusions))
        if not replaying:
            report['source_archive_closed'] = json.loads((root / 'sources/manifest.json').read_text())['archive_closed']
            if not report['source_archive_closed']:
                raise ValueError('Native run contains a recording failure; source archive is not replayable')
    except Exception as exc:
        report.update(complete=False, error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
    finally:
        if collector:
            report.update(observed_occurrences=len(collector.occurrences),
                ui_responses=len(collector.responses), date_exclusions=len(collector.date_exclusions))
            try:
                collector.persist_observations()
                report['partial_or_complete_observations_saved'] = True
            except Exception as exc:
                report.update(complete=False, observation_archive_error=type(exc).__name__ + ': ' + str(exc),
                    observation_archive_traceback=traceback.format_exc())
            finally:
                try:
                    collector.h.close()
                except Exception as exc:
                    report.update(complete=False, close_error=type(exc).__name__ + ': ' + str(exc))
        write(root / 'acquisition.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('collector_sha256','traceback')}, ensure_ascii=False))
    if not report['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
