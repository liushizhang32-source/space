import argparse,json,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse,Response
from orchestrator.ipad_app import create_app,Devices
from orchestrator.bailian_app import default_root

def main():
    root=Path(__file__).resolve().parents[1];config=json.loads((root/'.runtime/ipad-network.json').read_bytes())
    devices=Devices(default_root()/'ipad-security');devices.code=config['initial_pair_code'];devices.expires=config['pair_expires']
    app=create_app(devices=devices,hosts={config['ip'],'localhost','127.0.0.1'})
    bootstrap=FastAPI(docs_url=None,openapi_url=None)
    @bootstrap.get('/')
    def setup():return HTMLResponse(f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><h1>首次连接纸书智伴</h1><p>此HTTP入口仅提供公开CA，不提供绘本、Key、设备会话或业务API。</p><p>先与电脑显示的CA指纹比对：{config['fingerprint']}</p><a href="/ca.cer">下载本家庭公开CA证书</a><p>安装描述文件后：设置→通用→关于本机→证书信任设置→完全信任 Paperbook Household Local CA。</p><a href="{config['url']}">完成信任后打开HTTPS应用</a><p>随后输入电脑上的五分钟配对码。</p></html>''')
    @bootstrap.get('/ca.cer')
    def ca():return Response(Path(config['public_ca']).read_bytes(),media_type='application/x-x509-ca-cert',headers={'Content-Disposition':'attachment; filename="paperbook-ca.cer"','Cache-Control':'no-store'})
    setupserver=uvicorn.Server(uvicorn.Config(bootstrap,host=config['ip'],port=config['setup_port'],access_log=False,proxy_headers=False))
    server=uvicorn.Server(uvicorn.Config(app,host=config['ip'],port=config['port'],ssl_certfile=config['cert'],ssl_keyfile=config['key'],access_log=False,proxy_headers=False))
    app.state.request_shutdown=lambda:(setattr(server,'should_exit',True),setattr(setupserver,'should_exit',True))
    thread=threading.Thread(target=setupserver.run,daemon=True);thread.start()
    try:server.run()
    finally:setupserver.should_exit=True;thread.join(10)
if __name__=='__main__':main()
