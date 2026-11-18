import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.ipad_network import prepare
from orchestrator.bailian_app import default_root
c=prepare(default_root()/'ipad-security','127.0.0.1');print(c['ca'])
