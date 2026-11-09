"""Functional test guard: no provider SDKs, external network or arbitrary processes.

This is a misuse guard for reviewed project code, not a hostile-code sandbox.
"""
import importlib.abc
import json
import os
from pathlib import Path
import runpy
import shlex
import sys

CONTROL = Path(__file__).resolve().parent
TARGET = Path(os.environ['CI_TARGET']).resolve()
OUT = Path(os.environ['CI_RUN_DIR']).resolve()
VENDOR = TARGET/'orchestrator/vendor/member3_v116'
MODE = sys.argv[1]
denied = []
media_calls = []


def writable(path, dir_fd=None):
    if path is None or isinstance(path, int):
        return True
    try:
        candidate = Path(os.fsdecode(path).removeprefix('\\\\?\\'))
        if dir_fd not in (None, -1) and not candidate.is_absolute():
            # Linux's fd-based rmtree emits relative names; check their real parent.
            candidate = Path(os.readlink('/proc/self/fd/'+str(dir_fd)))/candidate
        resolved = candidate.resolve()
        return resolved.is_relative_to(OUT) or resolved.is_relative_to(VENDOR/'_test_tmp')
    except (ValueError, TypeError, OSError):
        return False


def audit(event, args):
    if event == 'subprocess.Popen':
        executable = Path(os.fsdecode(args[0]) if args[0] is not None else
                          shlex.split(args[1], posix=False)[0].strip('"')).resolve()
        tools = {Path(os.environ[k]).resolve() for k in ('FFMPEG_PATH', 'FFPROBE_PATH')}
        if executable in tools and not any(p in str(args[1]).lower() for p in
                ('http://', 'https://', 'tcp://', 'udp://', 'rtsp://', 'ftp://')):
            media_calls.append(executable.name)
            return
        # Only the trusted HTTP harness can spawn the guarded Uvicorn wrapper.
        command = (list(args[1]) if isinstance(args[1], (list, tuple)) else
                   [p.strip('"') for p in shlex.split(args[1], posix=False)])
        if (MODE == 'http' and executable == Path(sys.executable).resolve()
                and len(command) == 3 and Path(command[1]).resolve() == CONTROL/'guard.py'
                and command[2] == 'server'):
            return
    if event in ('socket.connect', 'socket.connect_ex'):
        if isinstance(args[1], tuple) and args[1][0] in ('127.0.0.1', '::1'):
            return
    if event in ('socket.getaddrinfo', 'socket.gethostbyname') and args[0] in ('127.0.0.1', '::1', 'localhost'):
        return
    if event == 'urllib.Request':
        from urllib.parse import urlsplit
        if urlsplit(args[0]).hostname in ('127.0.0.1', '::1'):
            return
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'socket.gethostbyname', 'socket.sendto', 'urllib.Request',
                 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        denied.append(event)
        raise PermissionError('CI isolation denied '+event)
    if event == 'open':
        path, mode, flags = args
        write = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if write and not writable(path):
            raise PermissionError('CI write outside test directory')
        if not write and not isinstance(path, int) and Path(path).name == '.env' and not writable(path):
            raise PermissionError('CI cannot read real .env')
    if event in ('os.remove', 'os.rmdir', 'os.mkdir', 'shutil.rmtree'):
        fd_index = 2 if event == 'os.mkdir' else 1
        fd = args[fd_index] if len(args) > fd_index else None
        if not writable(args[0], fd):
            raise PermissionError('CI mutation outside test directory: '+str(args[0]))
    if event in ('os.rename', 'os.replace'):
        fds = args[2:4] if len(args) >= 4 else (None, None)
        if not all(writable(p, fd) for p, fd in zip(args[:2], fds)):
            raise PermissionError('CI rename outside test directory')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'paddle', 'paddleocr', 'torch', 'ultralytics',
                                    'transformers', 'openai'}:
            raise ImportError('Real model imports disabled in CI')


sys.dont_write_bytecode = True
sys.meta_path.insert(0, NoModels())
sys.addaudithook(audit)
sys.path[:0] = [str(CONTROL/'member3'), str(VENDOR), str(TARGET)]
sys.argv = sys.argv[2:]
try:
    if MODE == 'pytest':
        import pytest
        raise SystemExit(pytest.main(sys.argv))
    elif MODE in ('prepare', 'http', 'server'):
        filename = {'prepare': 'prepare_fixtures.py', 'http': 'http_check.py',
                    'server': 'http_server.py'}[MODE]
        sys.argv = [str(CONTROL/filename)]
        runpy.run_path(str(CONTROL/filename), run_name='__main__')
    else:
        raise ValueError('Unknown guard mode')
finally:
    (OUT/('guard-'+MODE+'.json')).write_text(json.dumps({
        'denied_events': denied, 'allowed_media_processes': len(media_calls)}), encoding='utf-8')
