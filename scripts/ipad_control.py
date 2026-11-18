import getpass,json,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if sys.argv[-1]=='reset-pin':
    from orchestrator.ipad_app import Devices
    from orchestrator.bailian_app import default_root
    first=getpass.getpass('New parent PIN (8+): ');second=getpass.getpass('Repeat: ')
    if first!=second:raise ValueError('PIN mismatch')
    Devices(default_root()/'ipad-security').set_pin(first);print('Parent PIN updated locally.');raise SystemExit(0)
root=Path(__file__).resolve().parents[1];config=json.loads((root/'.runtime/ipad-network.json').read_bytes())
with httpx.Client(base_url=config['url'],verify=config['ca'],trust_env=False,timeout=180) as c:
    print(c.get('/health').json())
    if sys.argv[-1]=='stop':
        r=c.post('/ipad/login',json={'pin':getpass.getpass('Parent PIN: ')});r.raise_for_status();c.headers['X-iPad-CSRF']=r.json()['csrf']
        r=c.get('/studio/session');r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];r=c.post('/studio/shutdown',json={});r.raise_for_status();print(r.json())
