import hashlib,io,json,os,socket,ssl,threading,time
from pathlib import Path
import httpx,pytest,uvicorn
from fastapi.testclient import TestClient
from PIL import Image
from orchestrator.ipad_app import create_app,Devices
from orchestrator.services.bailian.engine import BookEngine

def image():
    out=io.BytesIO();Image.new('RGB',(640,480),'ivory').save(out,format='PNG');return out.getvalue()
@pytest.fixture
def household(tmp_path):
    d=Devices(tmp_path/'devices');d.set_pin('test-parent-123');e=BookEngine(tmp_path/'m1')
    app=create_app(engine=e,devices=d,hosts={'localhost','testserver','127.0.0.1'})
    yield app,d,e
    e.close()
def login(c):
    r=c.post('/ipad/login',json={'pin':'test-parent-123'});assert r.status_code==200;c.headers['X-iPad-CSRF']=r.json()['csrf'];c.headers['X-CSRF-Token']=c.get('/studio/session').json()['csrf']
def pair(c,d):
    r=c.post('/ipad/pair',json={'code':d.pairing(),'name':'test iPad'});assert r.status_code==200;c.headers['X-iPad-CSRF']=r.json()['csrf'];c.headers['X-CSRF-Token']=c.get('/studio/session').json()['csrf'];return r

@pytest.mark.parametrize('path',['/ipad/books','/studio/jobs','/studio/config','/studio/assets/input/a.jpg','/demo/demo.mp4'])
def test_unpaired_cannot_read_private_data(household,path):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:assert c.get(path).status_code==401
def test_http_and_dns_rebinding_denied(household):
    a,d,e=household
    with TestClient(a,base_url='http://testserver') as c:assert c.get('/').status_code==403
    with TestClient(a,base_url='https://evil.example') as c:assert c.get('/').status_code==403
def test_parent_and_child_boundaries_and_revocation(household):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as parent,TestClient(a,base_url='https://testserver') as child:
        login(parent);pair(child,d)
        for path in ['/studio/config','/studio/connections','/studio/generate','/ipad/parent/pairing','/studio/questions']:
            r=child.get(path) if path=='/studio/config' else child.post(path,json={});assert r.status_code==403
        assert 'secure' in str(child.cookies).lower() or child.get('/ipad/session').status_code==200
        did=next(iter(d.data['devices']));assert parent.post('/ipad/parent/revoke',json={'device':did}).status_code==200
        assert child.get('/ipad/books').status_code==401
def test_pair_code_one_use_expiry_and_rate_limit(household):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:
        code=d.pairing();r=c.post('/ipad/pair',json={'code':code});assert r.status_code==200
        assert c.post('/ipad/pair',json={'code':code}).status_code==403
        code=d.pairing();d.expires=0;assert c.post('/ipad/pair',json={'code':code}).status_code==403
        for i in range(8):r=c.post('/ipad/login',json={'pin':'wrong'})
        assert r.status_code==429
def test_csrf_cross_origin_and_child_no_paid_approval(household):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:
        pair(c,d);assert c.post('/ipad/ocr/not-real',json={},headers={'X-iPad-CSRF':'wrong'}).status_code==403
        assert c.get('/ipad/books',headers={'Origin':'https://evil.example'}).status_code==403
        assert c.post('/ipad/ask',json={'page_no':1,'question':'你好'}).status_code==403
        assert e.authority.m1.totals()['held']==0
def test_no_key_upload_pdf_heic_and_private_range(household):
    import pymupdf,pillow_heif
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:
        pair(c,d)
        book=c.post('/studio/books',files=[('files',('a.png',image(),'image/png'))]).json();assert len(book['pages'])==1
        url='/studio/assets/'+book['pages'][0]['asset'];raw=c.get(url).content
        assert c.get(url,headers={'Range':'bytes=5-12'}).content==raw[5:13]
        with pymupdf.open() as pdf:
            pdf.new_page();pdf.new_page();data=pdf.tobytes()
        assert len(c.post('/studio/books',files=[('files',('a.pdf',data,'application/pdf'))]).json()['pages'])==2
        out=io.BytesIO();pillow_heif.from_pillow(Image.new('RGB',(400,300),'white')).save(out)
        assert c.post('/studio/books',files=[('files',('a.heic',out.getvalue(),'image/heic'))]).status_code==200
        assert e.authority.m1.totals()=={'spent':0,'held':0,'available':15000}
def test_service_worker_caches_only_public_shell(household):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:
        sw=c.get('/sw.js').text;assert "SHELL=['/','/app.js','/style.css','/icon.svg','/manifest.webmanifest']" in sw
        assert "!SHELL.includes(u.pathname)" in sw and 'localStorage' not in c.get('/app.js').text
        manifest=c.get('/manifest.webmanifest').json();assert manifest['display']=='standalone' and manifest['orientation']=='any'
        assert 'capture="environment"' in c.get('/').text
def test_parent_key_not_echoed_and_lock(household):
    a,d,e=household
    with TestClient(a,base_url='https://testserver') as c:
        login(c);secret='fake-only-unit-secret';r=c.post('/studio/config',json={'config':e.config.model_dump(),'api_key':secret})
        assert r.status_code==200 and secret not in r.text
        assert c.post('/ipad/lock',json={}).status_code==200 and c.get('/studio/config').status_code==401
    assert all(secret.encode() not in p.read_bytes() for p in e.authority.root.rglob('*') if p.is_file())

@pytest.mark.parametrize('size',[(768,1024),(1024,768),(820,1180),(1180,820)])
def test_webkit_ipad_layout_upload_demo(household,tmp_path,size):
    from playwright.sync_api import sync_playwright,expect
    from orchestrator.bailian_app import default_root
    a,d,e=household;tls=default_root()/'ipad-security'
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(a,host='127.0.0.1',port=port,ssl_certfile=str(tls/'server.crt'),ssl_keyfile=str(tls/'server.key'),access_log=False,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        # Verify real TLS chain/SAN independently; browser context uses the
        # installed local household CA, no ignoreHTTPSErrors bypass.
        with httpx.Client(verify=str(tls/'paperbook-ca.crt'),trust_env=False) as client:assert client.get(f'https://127.0.0.1:{port}/health').status_code==200
        with sync_playwright() as pw:
            b=pw.webkit.launch();context=b.new_context(viewport={'width':size[0],'height':size[1]},has_touch=True,is_mobile=True,device_scale_factor=2)
            page=context.new_page();media_responses=[];page.on('response',lambda r:media_responses.append((r.status,r.headers)) if '/demo/' in r.url else None);page.goto(f'https://127.0.0.1:{port}');page.locator('#pairCode').fill(d.pairing());page.locator('#pair').click();expect(page.locator('#auth')).to_be_hidden()
            for name in ['home','shelf','upload','generate','player','qa','parent']:
                page.evaluate('(name)=>location.hash=name',name);expect(page.locator('[data-page='+name+']')).to_be_visible();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.evaluate('location.hash="upload"');page.locator('#photos').set_input_files([{'name':'a.png','mimeType':'image/png','buffer':image()},{'name':'b.png','mimeType':'image/png','buffer':image()}]);expect(page.locator('.page')).to_have_count(2)
            page.evaluate('location.hash="home"');page.locator('#demo').click();expect(page.locator('#videoLabel')).to_contain_text('MOCK')
            for _ in range(100):
                if page.locator('#video').evaluate('(v)=>v.readyState')>=1:break
                page.wait_for_timeout(100)
            assert page.locator('#video').evaluate('(v)=>v.duration')>3.5,(media_responses,page.locator('#video').evaluate('(v)=>({error:v.error?.message,code:v.error?.code,canPlay:v.canPlayType("video/mp4"),src:v.currentSrc})'))
            assert page.locator('#video').get_attribute('playsinline') is not None
            assert page.evaluate('isSecureContext') is True
            out=Path(os.environ.get('IPAD_EVIDENCE',tmp_path));out.mkdir(exist_ok=True,parents=True);page.screenshot(path=str(out/f'webkit-{size[0]}x{size[1]}.png'),full_page=True)
            context.close();b.close()
    finally:server.should_exit=True;thread.join(30);assert not thread.is_alive()
