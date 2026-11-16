"""M1 launcher. No model imports or child creation before cgroup membership."""
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    (Path(sys.argv[1])/'cgroup.procs').write_text(str(os.getpid()))
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
