"""Test-only launch shim: imports the pinned, unmodified M2 worker CLI.

It supplies a source path, never substitutes a worker result or model response.
"""
import sys
source, request = sys.argv[1:]
sys.path.insert(0, source)
def deny(event,args):
    if event in {'socket.connect','socket.getaddrinfo'}:
        raise RuntimeError('OFFLINE_WORKER_NO_NETWORK')
sys.addaudithook(deny)
from vision.worker import main
raise SystemExit(main([request]))
