"""OS containment for a single trusted, configured worker command.

Windows: assign a SUSPENDED process to a non-breakaway, kill-on-close Job
Object, then resume it. Linux: require a delegated cgroup v2 with cgroup.kill.
Fail before executing model code when containment is unavailable. A process
group alone is insufficient (a descendant can call setsid).
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time


class ContainmentError(RuntimeError):
    """Do not clean workspace or start a replacement after failed drain."""


if os.name == 'nt':
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class Limits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active_limit', w.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Limits), ('io', IO), ('process_mem', ctypes.c_size_t),
                    ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                    ('peak_job', ctypes.c_size_t)]

    class Accounting(ctypes.Structure):
        _fields_ = [(n, ctypes.c_longlong) for n in ('user', 'kernel', 'period_user', 'period_kernel')]
        _fields_ += [(n, w.DWORD) for n in ('faults', 'total', 'active', 'terminated')]

    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('tid', w.DWORD),
                    ('pid', w.DWORD), ('base', w.LONG), ('delta', w.LONG), ('flags', w.DWORD)]

    for name, args, result in [
        ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
        ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
        ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
        ('CloseHandle', [w.HANDLE], w.BOOL),
        ('CreateToolhelp32Snapshot', [w.DWORD, w.DWORD], w.HANDLE),
        ('Thread32First', [w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
        ('Thread32Next', [w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
        ('OpenThread', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ('ResumeThread', [w.HANDLE], w.DWORD),
        ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
    ]:
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result

    def checked(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())


class WindowsTree:
    def __init__(self, argv, cwd, env, log):
        self.job = kernel.CreateJobObjectW(None, None)
        checked(self.job)
        self.process = None
        self.members = {}
        try:
            info = Extended()
            info.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no BREAKAWAY_OK
            checked(kernel.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)))
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW | 0x4)  # CREATE_SUSPENDED
            checked(kernel.AssignProcessToJobObject(self.job, int(self.process._handle)))
            self.observe()
            self._resume()
        except BaseException:
            if self.process is not None:
                # Also covers assign failure: suspended process cannot have descendants.
                kernel.TerminateJobObject(self.job, 1)
                self.process.kill()
                self.process.wait()
            kernel.CloseHandle(self.job)
            self.job = None
            for handle in self.members.values():
                kernel.CloseHandle(handle)
            raise

    def _resume(self):
        snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            present = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if entry.pid == self.process.pid:
                    thread = kernel.OpenThread(2, False, entry.tid)
                    checked(thread)
                    try:
                        if kernel.ResumeThread(thread) == 0xffffffff:
                            raise ctypes.WinError(ctypes.get_last_error())
                        return
                    finally:
                        kernel.CloseHandle(thread)
                present = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise ContainmentError('Suspended worker main thread not found')
        finally:
            kernel.CloseHandle(snapshot)

    def active(self):
        info = Accounting()
        checked(kernel.QueryInformationJobObject(self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.active

    def observe(self):
        # Retain actual process handles. Job active=0 can precede process-handle
        # signalling by a kernel teardown interval; it is not itself a wait.
        capacity = max(64, self.active()+16)
        while True:
            buffer = ctypes.create_string_buffer(8+capacity*ctypes.sizeof(ctypes.c_size_t))
            if kernel.QueryInformationJobObject(self.job, 3, buffer, len(buffer), None):
                count = ctypes.c_uint32.from_buffer(buffer, 4).value
                pids = (ctypes.c_size_t*count).from_buffer(buffer, 8)
                break
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        for pid in pids:
            if pid not in self.members:
                handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                if handle:
                    self.members[pid] = handle
                elif ctypes.get_last_error() != 87:  # PID already gone
                    raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self):
        # Prevent further descendant creation before the final membership
        # snapshot. Existing members survive setting a limit below their count;
        # any attempted new process would exceed this limit (even at count=1).
        info = Extended()
        info.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
        info.basic.active_limit = 1
        try:
            checked(kernel.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)))
            self.observe()
        finally:
            # Still kill the job if membership observation/limit setup fails.
            checked(kernel.TerminateJobObject(self.job, 1))

    def wait_members(self):
        end = time.monotonic()+10
        self.exit_witness = {}
        for pid, handle in self.members.items():
            milliseconds = max(0, int((end-time.monotonic())*1000))
            if kernel.WaitForSingleObject(handle, milliseconds) != 0:
                raise ContainmentError('Actual member handle did not signal; quarantine workspace')
            self.exit_witness[pid] = True

    def close(self):
        for handle in self.members.values():
            kernel.CloseHandle(handle)
        self.members.clear()
        if self.job is not None:
            kernel.CloseHandle(self.job)
            self.job = None


class LinuxTree:
    def __init__(self, argv, cwd, env, log, root):
        # This intentionally has no weaker process-group fallback.
        import uuid
        if root is None:
            raise ContainmentError('Linux requires a delegated cgroup-v2 root, not just setsid')
        root = Path(root).resolve(strict=True)
        if not (root/'cgroup.controllers').is_file():
            raise ContainmentError('Not a cgroup-v2 delegation')
        self.group = root/('m1-'+uuid.uuid4().hex)
        self.group.mkdir()
        self.process = None
        self.members = {}
        try:
            if not (self.group/'cgroup.kill').exists():
                raise ContainmentError('Kernel cgroup.kill unavailable')
            # The launcher joins BEFORE exec. It never creates children before joining.
            self.process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('_cgroup_exec.py')),
                str(self.group), *argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        except BaseException:
            self.group.rmdir()
            raise

    def active(self):
        return int(dict(line.split() for line in (self.group/'cgroup.events').read_text().splitlines())['populated'])

    def observe(self):
        # Retain pidfds rather than infer process death from PID reuse or kill(0).
        # The supplied delegated cgroup must be isolated from worker migration.
        import select
        for file in [self.group/'cgroup.procs', *self.group.glob('**/cgroup.procs')]:
            for pid in map(int, file.read_text().split()):
                old = self.members.get(pid)
                if old is None or select.select([old],[],[],0)[0]:
                    try:
                        handle = os.pidfd_open(pid)
                    except ProcessLookupError:
                        continue  # already exited, no running code/resources
                    if old is not None:
                        os.close(old)
                    self.members[pid] = handle

    def wait_members(self):
        import select
        end = time.monotonic()+10
        self.exit_witness = {}
        for pid, fd in self.members.items():
            if not select.select([fd],[],[],max(0,end-time.monotonic()))[0]:
                raise ContainmentError('cgroup member pidfd did not signal; quarantine workspace')
            self.exit_witness[pid] = True

    def terminate(self):
        self.observe()
        # Kill the launcher as well, including the pre-cgroup-join startup window.
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        (self.group/'cgroup.kill').write_text('1')

    def close(self):
        for fd in self.members.values():
            os.close(fd)
        self.members.clear()
        self.group.rmdir()


def start_tree(argv, cwd, env, log, *, cgroup_root=None):
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError('Worker must be a trusted argument list')
    if os.name == 'nt':
        return WindowsTree(argv, cwd, env, log)
    if sys.platform == 'linux':
        return LinuxTree(argv, cwd, env, log, cgroup_root)
    raise ContainmentError('No proven tree containment on this platform')


def drain(tree, *, kill=False):
    """Return only after root wait AND containment is empty. No cleanup on failure."""
    if kill or tree.active():
        tree.terminate()
    try:
        tree.process.wait(timeout=10)
        end = time.monotonic()+10
        while tree.active():
            if time.monotonic() >= end:
                raise ContainmentError('Process tree did not drain; quarantine workspace')
            time.sleep(.01)
        tree.wait_members()
    except subprocess.TimeoutExpired as exc:
        raise ContainmentError('Worker did not reap; quarantine workspace') from exc
    tree.close()
