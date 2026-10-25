"""Register the owned browser group before replacing this process with Chrome."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from edit.hd.tools.relation_browser_watchdog import _process_start_identity


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    pid = os.getpid()
    if os.getpgrp() != pid or os.getppid() != config['parent_pid']:
        raise RuntimeError('browser launch must belong to the current clock check')
    identity = _process_start_identity(pid)
    if identity is None:
        raise RuntimeError('browser process identity is unavailable')
    target = Path(config['work_directory']) / 'browser.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid': pid, 'identity': identity}))
    temporary.replace(target)
    # The parent kills Node before its final registry read. If Node died before
    # registration, this child must never start an unowned browser afterwards.
    if os.getppid() != config['parent_pid']:
        return 143
    os.execv(config['executable'], [config['executable'], *sys.argv[2:]])


if __name__ == '__main__':
    raise SystemExit(main())
