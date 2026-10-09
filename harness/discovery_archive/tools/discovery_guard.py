"""Task A filesystem/SQLite isolation and adapter-only live TCP (not an OS sandbox).
Derived from the qualified run_b guard; engineering guard remains unchanged.
"""
import os, sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

def guard_discovery(root, *, allow_live=False):
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
                
                import ipaddress
                from source_transport import public_source_io_active
                try:
                    public = ipaddress.ip_address(address[0]).is_global
                except (ValueError, TypeError, IndexError):
                    public = False
                if not (allow_live and public_source_io_active() and public and address[1] in (80, 443)):
                    raise PermissionError('Public source network is only allowed inside the recording adapter')
        elif event == 'socket.bind':
            address = args[1]
            if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] != 0:
                raise PermissionError('Only an ephemeral isolated loopback server is allowed')
    sys.addaudithook(audit)
