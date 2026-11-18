"""Owner CLI uses the same session/CSRF/quote/consent interfaces as the GUI."""
import argparse,json,time,uuid
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765');sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('connections');sub.add_parser('shutdown')
    g=sub.add_parser('generate');g.add_argument('--file',action='append',required=True,type=Path);g.add_argument('--title',default='我的绘本')
    g.add_argument('--age',choices=['3-6','6-9'],default='3-6');g.add_argument('--cost-limit',type=Decimal,default=0)
    g.add_argument('--approve-cloud-and-cost',action='store_true');g.add_argument('--account-permissions-confirmed',action='store_true');a=p.parse_args()
    with httpx.Client(base_url=a.url,timeout=120,trust_env=False) as client:
        r=client.get('/studio/session');r.raise_for_status();client.headers['X-CSRF-Token']=r.json()['csrf']
        def post(path,**kwargs):
            r=client.post(path,**kwargs)
            if not r.is_success:raise RuntimeError(r.json().get('error','REQUEST_FAILED'))
            return r.json()
        if a.action=='connections':print(json.dumps(post('/studio/connections',json={}),ensure_ascii=True));return
        if a.action=='shutdown':print(post('/studio/shutdown',json={}));return
        with ExitStack() as stack:
            files=[('files',(f.name,stack.enter_context(f.open('rb')))) for f in a.file]
            book=post('/studio/books',files=files)
        quote=post(f"/studio/books/{book['id']}/quote",json=dict(title=a.title,age=a.age))
        print(json.dumps(quote,ensure_ascii=True))
        if not a.approve_cloud_and_cost or not a.account_permissions_confirmed or a.cost_limit<=0:
            print('QUOTE_ONLY: no paid dispatch; use explicit consent, account confirmation and positive cost cap.');return
        job=post('/studio/generate',json=dict(quote_id=quote['id'],cap_fen=int(a.cost_limit*100),cloud_consent=True,
            account_permissions_confirmed=True,request_id=uuid.uuid4().hex))
        while job['status'] in {'QUEUED','RUNNING','CANCELLING'}:
            time.sleep(2);r=client.get('/studio/jobs/'+job['id']);r.raise_for_status();job=r.json();print(job['status'],job['stage'])
        print(json.dumps(job,ensure_ascii=True))
        if job['status']!='COMPLETED':raise RuntimeError('Generation did not complete: '+job['status'])
if __name__=='__main__':main()
