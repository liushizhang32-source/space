"""Local fault worker for M1 supervisor tests. Standard library only; no network."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='ok')
    parser.add_argument('--code', type=int, default=2002)
    parser.add_argument('--message', default='transient test fault')
    parser.add_argument('--transient', action='store_true')
    parser.add_argument('--evidence')
    parser.add_argument('request')
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding='utf-8'))
    keys = ('job_id', 'page_id', 'generation_id', 'input_revision', 'epoch', 'attempt_id', 'fencing_token')
    identity = {k: request[k] for k in keys}
    result = dict(protocol=request['protocol'], identity=identity, code=0, msg='ok', artifacts={})
    if args.mode in {'sleep', 'child', 'root_exit'}:
        import os
        child = None
        if args.mode in {'child', 'root_exit'}:
            child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(120)'])
        if args.evidence:
            Path(args.evidence).write_text(json.dumps(dict(root=os.getpid(), child=child.pid if child else None)))
        if args.mode != 'root_exit':
            time.sleep(120)
        # root_exit deliberately exits with a live descendant; job must kill it.
        else:
            return 0
    if args.mode == 'fail':
        result.update(code=args.code, msg=args.message, transient=args.transient)
    else:
        page_id = identity['page_id']
        book, number = page_id.rsplit('_p', 1)
        base = dict(schema_version='1.0', book_id=book, page_id=page_id, page_no=int(number),
                    image_width=96, image_height=128, elapsed_ms=1)
        if request['stage'] == 'ocr':
            c1 = dict(base, status='empty', text_blocks=[], page_confidence=0.0)
            c1_path=Path(request['outputs']['c1'])
            c1_path.parent.mkdir(parents=True,exist_ok=True)
            c1_path.write_text(json.dumps(c1), encoding='utf-8')
            result['artifacts'] = {'c1': request['outputs']['c1']}
            if args.mode == 'empty_error':
                result.update(code=3001,msg='No text detected')
        else:
            # VLM consumes only the separately materialized, M1-bound C1.
            c1_path = Path(request['inputs']['c1'])
            assert c1_path.parent == Path.cwd()
            assert hashlib.sha256(c1_path.read_bytes()).hexdigest() == request['c1_binding']['sha256']
            assert json.loads(c1_path.read_bytes())['page_id'] == page_id
            assert hashlib.sha256(Path(request['image_path']).read_bytes()).hexdigest() == request['image_sha256']
            c2 = dict(base, status='ok', description='local fixture', scene_tags=[],
                      objects=[dict(object_id=page_id+'_o01', label='球', bbox=[1, 1, 10, 10], confidence=.9)],
                      safety={'pass': True, 'flags': []})
            if args.mode == 'missing_safety':
                del c2['safety']
            elif args.mode == 'false_safety':
                c2['safety']['pass'] = False
            elif args.mode == 'string_safety':
                c2['safety']['pass'] = 'true'
            elif args.mode == 'bad_safety':
                c2['safety'] = []
            elif args.mode == 'numeric_safety':
                c2['safety']['pass'] = 1
            raw = json.dumps(c2, ensure_ascii=False).encode('utf-8')
            c2_path=Path(request['outputs']['c2'])
            c2_path.parent.mkdir(parents=True,exist_ok=True)
            c2_path.write_bytes(raw)
            refs = dict(schema_version='vision_refs/0.1', **identity,
                c2={'asset_id':'fixture-c2', 'schema_version':'1.0',
                    'relative_path':f'json/{page_id}_vlm.json', 'sha256':hashlib.sha256(raw).hexdigest()},
                source={'component_mode':'fixture', 'model_ref':'local-fake',
                        'prompt_sha256':hashlib.sha256(b'no model').hexdigest(), 'evidence_ref':'local-fake'},
                observations=[{'observation_id':'obs1', 'object_id':page_id+'_o01',
                    'appearance':{'visible_features':['圆形']}, 'visual_description':'local fixture',
                    'identity_status':'unknown', 'source_ref':'fixture',
                    'confidence':{'value':None, 'kind':'unavailable', 'calibrated':False}}])
            if args.mode == 'hash_mismatch':
                refs['c2']['sha256'] = '0'*64
            elif args.mode == 'foreign_object':
                refs['observations'][0]['object_id'] = 'book01_p04_o01'
            elif args.mode == 'sidecar_traversal':
                refs['c2']['relative_path'] = '../elsewhere.json'
            elif args.mode == 'old_refs':
                refs['generation_id'] = 'old-generation'
            Path(request['outputs']['sidecar']).write_text(json.dumps(refs), encoding='utf-8')
            result['artifacts'] = {k:request['outputs'][k] for k in ('c2','sidecar')}
        if args.mode == 'token_mismatch':
            result['identity']['fencing_token'] = 'wrong-token'
    Path(request['result_path']).write_text(json.dumps(result), encoding='utf-8')
    return 1 if args.mode in {'fail','empty_error'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
