from __future__ import annotations
import contextlib, fcntl, hashlib, json, os, re, shutil, sqlite3, threading, time, unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
from datetime import datetime, timezone
PROFILE_MARKER = '.gewu_disposable_profile.json'
RUN_ROOT = None
BENCHMARK_ROOT = Path(__file__).resolve().parents[1]

def ensure_profile_path(path):
    path=Path(path).resolve()
    if RUN_ROOT is None or not path.is_relative_to(RUN_ROOT):
        raise ValueError('Not inside active V4 disposable run')
    return path

def is_relative_to(path, root): return Path(path).resolve().is_relative_to(Path(root).resolve())
def utc_now(): return datetime.now(timezone.utc).isoformat()
def read_json(path): return json.loads(Path(path).read_text())
def canonical_json(obj): return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha256_bytes(data): return hashlib.sha256(data).hexdigest()
def sha256_file(path): return sha256_bytes(Path(path).read_bytes())
def write_json_new(path, obj):
    path=ensure_profile_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(obj,f,ensure_ascii=False,indent=2,default=str);f.write('\n')
def load_config(): return {'schema_version':'4.1-qualification-schema22'}
def assert_port_available(port):
    if port != 0: raise ValueError('Only ephemeral ports allowed')

class ApiServer:
    """Current authenticated workspace API on a disposable ephemeral port."""
    def __init__(self,profile,port=0):
        self.profile=profile;self.server=None;self.port=0
    def __enter__(self):
        from paper_monitor import ui_server
        profile=self.profile
        class Handler(ui_server.PaperMonitorUiHandler):
            configured_db_path=profile.db
            configured_journals=[j['name'] for j in read_json(profile.config/'journals.json')['journals']]
            def log_message(self,*args):pass
        self.server=ui_server.FastLocalThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        if self.get_json('/api/health').get('ok') is not True:
            self.__exit__(None,None,None);raise RuntimeError('Isolated API unhealthy')
        return self
    def __exit__(self,*args):
        if self.server:self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,query=None,payload=None,text=False):
        import http.client
        from urllib.parse import urlencode
        suffix=('?'+urlencode(query)) if query else ''
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=20)
        headers={'X-Gewu-Workspace':self.server.workspace_access.token,'Content-Type':'application/json'}
        connection.request('POST' if payload is not None else 'GET',path+suffix,
            json.dumps(payload) if payload is not None else None,headers)
        response=connection.getresponse();body=response.read();connection.close()
        if response.status!=200:raise RuntimeError('Workspace API '+path+' returned '+str(response.status)+': '+body.decode()[:500])
        return body.decode() if text else json.loads(body)
    def get_json(self,path,query=None):return self.request(path,query)
    def get_text(self,path='/'):return self.request(path,text=True)
    def post_json(self,path,payload):return self.request(path,payload=payload)
def expected_paper_resource_visibility(
    paper: dict[str, Any],
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Independently classify SQLite resources that the Paper Files API should expose.

    SQLite intentionally retains auditable predecessor rows after some legacy
    backfills and path repairs.  The product UI hides only predecessors that can
    be proven stale.  Task C therefore compares the HTTP resource set with this
    contract projection instead of requiring the API to echo every raw row.
    """

    primary_id = int(paper.get("primary_resource_id") or 0)
    preferred_id = int(paper.get("preferred_resource_id") or 0)
    materialized: list[dict[str, Any]] = []
    for raw in resources:
        resource = dict(raw)
        local_path = str(resource.get("stored_path") or resource.get("source_path") or "")
        resource["local_path"] = local_path
        resource["exists"] = bool(local_path and Path(local_path).expanduser().exists())
        resource["is_primary"] = int(resource.get("id") or 0) == primary_id
        resource["is_preferred"] = int(resource.get("id") or 0) == preferred_id
        materialized.append(resource)

    existing = [resource for resource in materialized if resource["exists"]]
    has_existing_legacy_backfill = any(
        str(resource.get("added_via") or "").strip().lower() == "legacy_backfill"
        and str(resource.get("file_role") or "").strip().lower() == "publication_version"
        for resource in existing
    )

    def filename_key(resource: dict[str, Any]) -> str:
        local_path = str(
            resource.get("local_path")
            or resource.get("stored_path")
            or resource.get("source_path")
            or ""
        ).strip()
        name = str(
            resource.get("display_name")
            or resource.get("original_filename")
            or Path(local_path).name
        ).strip()
        return unicodedata.normalize("NFKC", name).casefold()

    visible: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    for resource in materialized:
        resource_id = int(resource.get("id") or 0)
        if resource["exists"] or resource["is_primary"] or resource["is_preferred"]:
            visible.append(resource)
            continue
        role = str(resource.get("file_role") or "other").strip().lower()
        name = filename_key(resource)
        size = int(resource.get("size_bytes") or 0)
        exact_hash = str(resource.get("sha256") or "").strip()
        content_hash = str(resource.get("content_sha256") or "").strip()
        stale_alias = bool(
            role in {"", "other"}
            and has_existing_legacy_backfill
            and not str(resource.get("version_role") or "").strip()
            and not str(resource.get("added_via") or "").strip()
        )
        evidence = "untyped_predecessor_of_existing_legacy_backfill" if stale_alias else ""
        if role in {"", "other"} and name:
            for candidate in existing:
                if filename_key(candidate) != name:
                    continue
                same_hash = bool(
                    (exact_hash and exact_hash == str(candidate.get("sha256") or "").strip())
                    or (
                        content_hash
                        and content_hash == str(candidate.get("content_sha256") or "").strip()
                    )
                )
                same_legacy_file = bool(
                    size > 0
                    and size == int(candidate.get("size_bytes") or 0)
                    and str(candidate.get("file_role") or "").strip().lower()
                    == "publication_version"
                )
                if same_hash or same_legacy_file:
                    stale_alias = True
                    evidence = "missing_untyped_duplicate_of_existing_publication_resource"
                    break
        if stale_alias:
            hidden.append({"id": resource_id, "reason": evidence})
        else:
            visible.append(resource)

    return {
        "visible": visible,
        "visible_ids": [int(resource.get("id") or 0) for resource in visible],
        "hidden": hidden,
        "hidden_ids": [int(resource.get("id") or 0) for resource in hidden],
    }
    os.replace(temporary, path)


class HashChainJsonl:
    """Concurrent-safe append-only JSONL with a verifiable hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = ensure_profile_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_tail(self, handle: Any) -> tuple[int, str]:
        handle.seek(0)
        sequence = 0
        previous_hash = "0" * 64
        for line_number, raw in enumerate(handle, start=1):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Corrupt JSONL at {self.path}:{line_number}: {exc}") from exc
            if int(item.get("seq") or 0) != sequence + 1:
                raise RuntimeError(f"Non-contiguous JSONL sequence at {self.path}:{line_number}")
            if item.get("previous_event_hash") != previous_hash:
                raise RuntimeError(f"Broken JSONL previous hash at {self.path}:{line_number}")
            supplied = str(item.get("event_hash") or "")
            body = dict(item)
            body.pop("event_hash", None)
            calculated = sha256_bytes(canonical_json(body))
            if supplied != calculated:
                raise RuntimeError(f"Broken JSONL event hash at {self.path}:{line_number}")
            sequence = int(item["seq"])
            previous_hash = supplied
        return sequence, previous_hash

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        flags = os.O_RDWR | os.O_CREAT
        descriptor = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                sequence, previous_hash = self._read_tail(handle)
                body = dict(event)
                body["seq"] = sequence + 1
                body["recorded_at"] = body.get("recorded_at") or utc_now()
                body["previous_event_hash"] = previous_hash
                body["event_hash"] = sha256_bytes(canonical_json(body))
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return body
        except Exception:
            # fdopen owns and closes descriptor on every normal/error exit after construction.
            raise

    def audit(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"valid": True, "events": 0, "final_event_hash": "0" * 64}
        with self.path.open("r", encoding="utf-8") as handle:
            sequence, event_hash = self._read_tail(handle)
        return {"valid": True, "events": sequence, "final_event_hash": event_hash}


@dataclass(frozen=True)
class Profile:
    run_id: str
    root: Path

    @property
    def marker(self) -> Path:
        return self.root / PROFILE_MARKER

    @property
    def db(self) -> Path:
        return self.root / "data" / "paper_monitor.sqlite"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def library(self) -> Path:
        return self.data / "Library"

    @property
    def spaces(self) -> Path:
        return self.data / "Spaces"

    @property
    def publications(self) -> Path:
        return self.data / "My Publications"

    @property
    def associated(self) -> Path:
        return self.data / "Associated Files"

    @property
    def pdfs(self) -> Path:
        return self.data / "pdfs"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def raw_network(self) -> Path:
        return self.root / "raw_network"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def traces(self) -> Path:
        return self.root / "traces"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def trash(self) -> Path:
        return self.root / "trash"

    @property
    def audit_log(self) -> HashChainJsonl:
        return HashChainJsonl(self.logs / "execution_audit.jsonl")

    def verify(self) -> None:
        ensure_profile_path(self.root)
        if not self.marker.exists():
            raise RuntimeError(f"Missing benchmark profile marker: {self.marker}")
        marker = read_json(self.marker)
        if marker.get("run_id") != self.run_id or Path(marker.get("root", "")).resolve() != self.root.resolve():
            raise RuntimeError("Benchmark profile marker does not match requested profile")


@contextlib.contextmanager
def patched_product_roots(profile: Profile) -> Iterator[None]:
    profile.verify()
    from paper_monitor import ui_server

    def benchmark_trash(path: Path) -> Path:
        source = path.expanduser().resolve()
        if not is_relative_to(source, profile.root):
            raise RuntimeError(f"Refusing to trash path outside benchmark profile: {source}")
        target = profile.trash / source.name
        counter = 2
        while target.exists() or target.is_symlink():
            target = profile.trash / f"{source.stem} {counter}{source.suffix}"
            counter += 1
        source.replace(target)
        return target

    patches = [
        patch.object(ui_server, "LIBRARY_LOCAL_COPY_ROOT", profile.library),
        patch.object(ui_server, "MY_PUBLICATIONS_LOCAL_COPY_ROOT", profile.publications),
        patch.object(ui_server, "SPACES_LOCAL_COPY_ROOT", profile.spaces),
        patch.object(ui_server, "ASSOCIATED_FILES_ROOT", profile.associated),
        patch.object(ui_server, "DEFAULT_PDF_DIR", profile.pdfs),
        patch.object(ui_server, "DEFAULT_LIBRARY_IMPORT_DIR", profile.data / "library_imports"),
        patch.object(ui_server, "PDF_THUMB_CACHE_DIR", profile.cache / "pdf_thumbs"),
        patch.object(ui_server, "WEBKIT_NETWORK_CACHE_DIR", profile.cache / "web"),
        patch.object(ui_server, "SUBJECTS_CONFIG_PATH", profile.config / "subjects.json"),
        patch.object(ui_server, "DEFAULT_COMMENT_REPORT_DIR", profile.reports / "citation_comments"),
        patch.object(ui_server, "PUBLICATION_EXPORT_DIR", profile.reports / "publication_exports"),
        patch.object(ui_server, "move_path_to_macos_trash", benchmark_trash),
    ]
    for active in patches:
        active.start()
    try:
        yield
    finally:
        for active in reversed(patches):
            active.stop()


def filesystem_inventory(roots: list[Path]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for root in roots:
        root = ensure_profile_path(root)
        if not root.exists():
            inventory.append({"root": str(root), "exists": False})
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file() or item.is_symlink()):
            stat = path.lstat()
            item: dict[str, Any] = {
                "root": str(root),
                "path": str(path.relative_to(root)),
                "size": stat.st_size,
                "is_symlink": path.is_symlink(),
            }
            if path.is_symlink():
                item["target"] = os.readlink(path)
                item["target_exists"] = path.exists()
            else:
                item["sha256"] = sha256_file(path)
            inventory.append(item)
    return inventory
