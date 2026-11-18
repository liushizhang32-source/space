"""Private CLI for the existing M1 WindowsTree supervisor, never an HTTP API."""
import json,subprocess,sys
from pathlib import Path

def main():
    spec=json.loads(Path(sys.argv[1]).read_bytes())
    with open(spec['stdin'],'rb') as inp,open(spec['stdout'],'wb') as out:
        # Parent M1 creates this process suspended inside its kill-on-close Job
        # Object. This native child inherits the same non-breakaway boundary.
        result=subprocess.run(spec['command'],cwd=spec['cwd'],stdin=inp,stdout=out,stderr=sys.stderr)
    return result.returncode
if __name__=='__main__':raise SystemExit(main())
