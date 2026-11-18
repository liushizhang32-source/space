"""One Windows local studio process, graceful shutdown owns and awaits workers."""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from orchestrator.bailian_app import create_app,default_root

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);a=p.parse_args()
    root=default_root();root.mkdir(parents=True,exist_ok=True)
    # Separate retained lock, not deleted or a reset option for the budget.
    lock=(root/'studio.instance.lock').open('a+b');lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    app=create_app();server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=a.port,access_log=False))
    app.state.request_shutdown=lambda:setattr(server,'should_exit',True)
    try:server.run()
    finally:lock.close()
if __name__=='__main__':main()
