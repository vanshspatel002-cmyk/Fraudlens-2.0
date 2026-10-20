"""Private evidence filesystem checks; never call an AI/provider endpoint."""
import os
from pathlib import Path
import tempfile


def check_storage_ready(upload_dir, thumbnail_dir):
    configured = os.environ.get('FRAUDLENS_PERSISTENT_ROOT')
    volume = Path(configured).resolve() if configured else None
    if volume is not None and (not Path(configured).is_absolute() or not volume.is_dir()):
        raise OSError('Persistent volume unavailable')
    for directory in (Path(upload_dir), Path(thumbnail_dir)):
        if volume is not None and (not directory.is_absolute() or not directory.resolve().is_relative_to(volume)):
            raise OSError('Evidence path is outside the persistent volume')
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory) as probe:
            probe.write(b'fraudlens-storage-check')
            probe.flush()
