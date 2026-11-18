"""M1 controlled launch shim for the committed, unmodified M2 offline worker.

The frozen V1 worker allows fixture/stub only. Real backends require a separately
approved profile; this shim never supplies model responses or replaces a module.
"""
import sys
from pathlib import Path
source=Path(__file__).resolve().parents[2]/'paperbook-ai-m2/paperbook-ai/src'
sys.path.insert(0,str(source))
def deny(event,args):
    if event in {'socket.connect','socket.getaddrinfo'}:raise RuntimeError('FROZEN_OFFLINE_WORKER_NO_NETWORK')
sys.addaudithook(deny)
from vision.worker import main
raise SystemExit(main([sys.argv[1]]))
