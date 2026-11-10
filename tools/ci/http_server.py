from pathlib import Path
import os,threading,time
import uvicorn
from orchestrator.main import app

ROOT=Path(os.environ['CI_RUN_DIR'])
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(os.environ['INTEGRATION_PORT']),
                                   log_level='warning',access_log=False))
def stop():
    while not (ROOT/'stop-http').exists() and not server.should_exit:time.sleep(.1)
    server.should_exit=True
threading.Thread(target=stop,daemon=True).start()
server.run()
