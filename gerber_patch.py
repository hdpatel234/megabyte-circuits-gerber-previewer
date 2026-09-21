import gerber
import gerber.common

# Patch pcb-tools gerber.read to avoid Python 3.11+ 'rU' mode deprecation error
if not getattr(gerber, "_patched_rU", False):
    def _patched_read(filename):
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            data = f.read()
        return gerber.loads(data, str(filename))

    gerber.read = _patched_read
    gerber.common.read = _patched_read
    gerber._patched_rU = True
