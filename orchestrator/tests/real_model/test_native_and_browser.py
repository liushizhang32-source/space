"""Actual local OCR/OpenCV/FFmpeg and actual Chromium HTTP interactions.

Only cloud HTTP is mocked. No keys or paid requests are needed or accepted.
"""
import hashlib,io,json,os,socket,subprocess,threading,time
from pathlib import Path
import httpx,pytest,uvicorn
from PIL import Image,ImageDraw,ImageFont
from orchestrator.bailian_app import create_app
from orchestrator.services.bailian.engine import BookEngine
from orchestrator.services.bailian.local import LocalTools,run
from conftest import CloudFixture,start_book,finish

def text_page(font):
    image=Image.new('RGB',(1000,700),'white');draw=ImageDraw.Draw(image);face=ImageFont.truetype(font,60)
    draw.text((70,80),'小兔子在森林里散步。',font=face,fill='black');draw.text((70,200),'今天阳光很好。',font=face,fill='black')
    b=io.BytesIO();image.save(b,format='PNG');return b.getvalue()

def test_real_paddle_ocr_and_frozen_coordinates(native_media):
    tools=native_media['tools'];raw=text_page(tools.font);result=tools.ocr(raw)
    text=''.join(r['text'] for r in result['lines'])
    assert '小兔子在森林里散步。' in text and '今天阳光很好。' in text
    assert result['source_mode']=='REAL_LOCAL' and result['opencv_version']
    assert all(0<=r['bbox'][0]<r['bbox'][2]<=1000 and 0<=r['bbox'][1]<r['bbox'][3]<=700 for r in result['lines'])
    evidence=os.environ.get('REAL_MODEL_EVIDENCE_DIR')
    if evidence:
        p=Path(evidence);p.mkdir(parents=True,exist_ok=True);(p/'real-paddle-input.png').write_bytes(raw)
        (p/'real-paddle.json').write_text(json.dumps(dict(**result,input_sha256=hashlib.sha256(raw).hexdigest()),ensure_ascii=False,indent=2),encoding='utf-8')

def test_real_opencv_image_processing():
    import cv2,numpy as np
    image=np.full((160,220,3),255,np.uint8);cv2.rectangle(image,(50,30),(160,130),(30,70,90),-1)
    mask=np.zeros(image.shape[:2],np.uint8)
    cv2.grabCut(image,mask,(20,10,180,140),np.zeros((1,65)),np.zeros((1,65)),2,cv2.GC_INIT_WITH_RECT)
    foreground=((mask==1)|(mask==3)).astype(np.uint8)
    assert foreground[80,100] and not foreground[0,0] and int(foreground.sum())>8000
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);corrected=cv2.createCLAHE(2,(8,8)).apply(gray)
    assert corrected.shape==gray.shape and np.isfinite(corrected).all()
    from orchestrator.services.bailian.local import rectify_image
    photo=np.full((800,1000,3),30,np.uint8)
    cv2.fillConvexPoly(photo,np.array([[70,50],[920,110],[870,740],[120,740]],np.int32),(255,255,255))
    rectified,changed=rectify_image(Image.fromarray(photo))
    assert changed and rectified.width>700 and rectified.height>600
    assert rectified.getpixel((rectified.width//2,rectified.height//2))==(255,255,255)

def test_real_ocr_plus_mock_cloud_plus_real_media_end_to_end(tmp_path,native_media):
    tools=native_media['tools'];cloud=CloudFixture(native_media)
    engine=BookEngine(tmp_path/'real-ocr-state',local=tools,transport=httpx.MockTransport(cloud));engine._key='fixture-not-real'
    try:
        book=engine.upload([('chinese.png',text_page(tools.font))]);q=engine.quote(book['id'],'3-6','真实本地OCR')
        job=engine.generate(q['id'],q['estimate_fen'],True,True,'real-ocr-e2e');result=finish(engine,job)
        assert result['status']=='COMPLETED',result
        assert any('小兔子' in b['text'] for b in result['recognition'][0]['ocr']['text_blocks'])
        raw=engine.authority.read(result['outputs']['video'].removeprefix('/studio/assets/'),job=job['id'])[0]
        evidence=os.environ.get('REAL_MODEL_EVIDENCE_DIR')
        if evidence:
            p=Path(evidence);(p/'offline-e2e-MOCK-CLOUD.mp4').write_bytes(raw)
            (p/'offline-e2e.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:engine.close()

def test_browser_real_page_upload_quote_and_generate(rig,tmp_path):
    from playwright.sync_api import sync_playwright,expect
    engine,cloud=rig;app=create_app(engine=engine)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser_path=os.environ.get('BROWSER_EXECUTABLE')
            if not browser_path:
                candidates=[Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),Path('C:/Program Files/Google/Chrome/Application/chrome.exe')]
                browser_path=next((str(x) for x in candidates if x.is_file()),None)
            browser=pw.chromium.launch(headless=True,**({'executable_path':browser_path} if browser_path else {}))
            page=browser.new_page(viewport={'width':1360,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}');expect(page.locator('#notice')).to_contain_text('本地系统已连接')
            assert page.locator('#apiKey').get_attribute('type')=='password'
            page.locator('#files').set_input_files([dict(name='one.png',mimeType='image/png',buffer=__import__('conftest').image_bytes()),
                dict(name='two.png',mimeType='image/png',buffer=__import__('conftest').image_bytes('red'))])
            page.locator('.page').nth(1).wait_for();page.locator('.page button').nth(1).click();page.wait_for_timeout(500)
            page.locator('#bookTitle').fill('浏览器多页绘本');page.locator('#age').select_option('6-9');page.locator('#quote').click()
            page.locator('#approval').wait_for(state='visible');assert '¥' in page.locator('#estimate').inner_text()
            page.locator('#consent').check();page.locator('#permissions').check();page.locator('#generate').click()
            page.locator('#results').wait_for(state='visible',timeout=90000)
            for _ in range(100):
                if page.locator('#video').evaluate('(v)=>v.readyState')>=1:break
                page.wait_for_timeout(100)
            assert page.locator('#video').evaluate('(v)=>v.duration')>3.5
            assert page.locator('#downloadVideo').get_attribute('href').startswith('/studio/assets/output/')
            assert not page.evaluate('Object.keys(localStorage).length')
            assert not errors,errors
            evidence=Path(os.environ.get('REAL_MODEL_EVIDENCE_DIR',tmp_path));evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/'studio-browser-e2e.png'),full_page=True)
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=120);assert not thread.is_alive()
