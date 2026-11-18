"""Stage raw reports only, excluding ephemeral test keys/workspaces/media."""
import argparse,pathlib,shutil
parser=argparse.ArgumentParser();parser.add_argument('--source',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
for path in args.source.rglob('*'):
    relative=path.relative_to(args.source)
    if any(part.startswith('tmp-') or part in {'tmp','data','downloads','m2-exact','__pycache__','.upload','.pytest_cache'} for part in relative.parts):continue
    if path.is_file() and path.suffix in {'.xml','.json','.jsonl','.log','.txt'}:
        target=args.output/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
