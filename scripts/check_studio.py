"""Real native environment evidence. Never submits a cloud inference."""
import argparse,hashlib,io,json,os,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from orchestrator.services.bailian.local import LocalTools

def fixture(font):
    im=Image.new('RGB',(1000,700),'white');d=ImageDraw.Draw(im);f=ImageFont.truetype(font,60)
    d.text((70,80),'小兔子在森林里散步。',font=f,fill='black');d.text((70,200),'今天阳光很好。',font=f,fill='black')
    out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
def main():
    p=argparse.ArgumentParser();p.add_argument('--warm-ocr',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise RuntimeError('Never overwrite environment evidence; choose a new output')
    tools=LocalTools();status=tools.status();result=dict(status=status,real_cloud_model_test='WAITING_FOR_KEY',production_ready=False)
    import cv2,numpy as np,dashscope,pymupdf
    assert callable(cv2.grabCut);sample=np.zeros((100,100,3),np.uint8);sample[20:80,20:80]=255
    mask=np.zeros((100,100),np.uint8);cv2.grabCut(sample,mask,(10,10,80,80),np.zeros((1,65)),np.zeros((1,65)),1,cv2.GC_INIT_WITH_RECT)
    assert np.count_nonzero(mask==3)>1000
    result.update(opencv_real_test='PASS',opencv_version=cv2.__version__,dashscope_version=dashscope.__version__)
    if 'MISSING' in status.values():raise RuntimeError('Missing local native tools')
    if a.warm_ocr:
        raw=fixture(tools.font);ocr=tools.ocr(raw)
        text=''.join(x['text'] for x in ocr['lines'])
        assert '小兔子在森林里散步' in text and '今天阳光很好' in text
        result.update(paddleocr_real_test='PASS',ocr=ocr,input_sha256=hashlib.sha256(raw).hexdigest())
        a.output.with_suffix('.input.png').write_bytes(raw)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='ocr'},ensure_ascii=True))
if __name__=='__main__':main()
