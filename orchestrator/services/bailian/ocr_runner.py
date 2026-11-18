"""Isolated PaddleOCR process. stdout is exactly one machine-readable result.

Only small official PP-OCRv5 mobile detection/recognition weights are loaded.
No cloud credentials or user-selected paths are accepted on this CLI.
"""
import contextlib,hashlib,io,json,os,sys,time
from pathlib import Path

def verify_weights():
    lock=Path(__file__).resolve().parents[3]/'config/paddle-model-sha256.json'
    expected=json.loads(lock.read_bytes());root=Path.home()/'.paddlex/official_models'
    for model,files in expected.items():
        for name,sha in files.items():
            if hashlib.sha256((root/model/name).read_bytes()).hexdigest()!=sha:raise ValueError('OCR_MODEL_SHA256_MISMATCH')

def recognize(raw):
    import cv2,numpy as np
    from paddleocr import PaddleOCR
    from PIL import Image
    original=Image.open(io.BytesIO(raw)).convert('RGB')
    pixels=np.asarray(original)
    # Capture already normalizes EXIF orientation/perspective. Contrast correction
    # here preserves geometry, so C1 uses those same canonical original pixels.
    lab=cv2.cvtColor(pixels,cv2.COLOR_RGB2LAB)
    lab[:,:,0]=cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(lab[:,:,0])
    corrected=cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)
    model=PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='PP-OCRv5_mobile_rec',
        use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,
        enable_mkldnn=False,cpu_threads=4)
    verify_weights()
    rows=[]
    for result in model.predict(corrected):
        data=result.json
        if isinstance(data,str):data=json.loads(data)
        data=data.get('res',data)
        for text,score,poly in zip(data.get('rec_texts',[]),data.get('rec_scores',[]),data.get('rec_polys',[])):
            pts=np.asarray(poly);x1,y1=pts.min(axis=0);x2,y2=pts.max(axis=0)
            box=[max(0,int(x1)),max(0,int(y1)),min(original.width,int(x2)),min(original.height,int(y2))]
            if text.strip() and box[2]>box[0] and box[3]>box[1]:
                rows.append(dict(text=text,bbox=box,confidence=float(score)))
    rows.sort(key=lambda r:(r['bbox'][1]//16,r['bbox'][0]))
    return dict(width=original.width,height=original.height,lines=rows,backend='PaddleOCR/PP-OCRv5-mobile',
        opencv_version=cv2.__version__,source_mode='REAL_LOCAL')

def main():
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
    raw=sys.stdin.buffer.read(25*1024*1024)
    started=time.monotonic()
    with contextlib.redirect_stdout(sys.stderr):result=recognize(raw)
    result['elapsed_ms']=int((time.monotonic()-started)*1000)
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())
if __name__=='__main__':main()
