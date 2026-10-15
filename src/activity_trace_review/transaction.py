"""Linux no-replace publication. The hook is for deterministic fault tests only."""
import ctypes
import errno
import os
from pathlib import Path
import sys
import tempfile
from .validate import validate_bundle, validate_files

STAGES = ('staging_created', 'file_written', 'files_synced', 'validated',
          'directory_synced', 'before_publish', 'published', 'parent_synced')

class ExportError(OSError):
    pass


def _rename_noreplace(parent_fd, old, new):
    if sys.platform != 'linux':
        raise OSError(errno.ENOTSUP, 'Atomic export requires Linux renameat2')
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as e:
        raise OSError(errno.ENOTSUP, 'libc renameat2 is unavailable') from e
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(old), parent_fd, os.fsencode(new), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def publish_bundle(files, destination, budget, *, hook=None):
    """Return only after validation, no-replace rename and parent fsync succeed."""
    hook = hook or (lambda stage, path: None)
    budget.check()
    # Validate before touching disk as well as independently rereading staged bytes.
    validate_files(files)
    dest = Path(os.path.abspath(destination))
    if any(part.startswith('.trace-stage-') for part in (*dest.parts, *dest.resolve().parts)):
        raise ExportError('Reserved staging name; choose another destination')
    if sys.platform != 'linux':
        raise ExportError('Atomic export requires Linux renameat2; no output created')
    parent_fd = None
    stage = None
    published = False
    rename_started = False
    try:
        parent_fd = os.open(dest.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if os.path.lexists(dest):
            raise FileExistsError(errno.EEXIST, 'Output already exists', str(dest))
        # Probe directory fsync before producing artifacts; rename flag support is
        # determined by the actual atomic operation, never by a racy preflight.
        os.fsync(parent_fd)
        stage = Path(tempfile.mkdtemp(prefix='.trace-stage-', dir=dest.parent))
        (stage/'INCOMPLETE').write_text('Not a published bundle. See docs/transactions.md for recovery.\n')
        payload = stage/'payload'
        payload.mkdir(mode=0o700)
        hook('staging_created', stage)
        for name, data in sorted(files.items()):
            budget.check()
            fd = os.open(payload/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                hook('file_written', stage)
                os.fsync(stream.fileno())
        hook('files_synced', stage)
        validate_bundle(payload, _staged=True)
        hook('validated', stage)
        fd = os.open(payload, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        hook('directory_synced', stage)
        budget.check()
        hook('before_publish', stage)
        rename_started = True
        _rename_noreplace(parent_fd, stage.name+'/payload', dest.name)
        published = True
        hook('published', stage)
        os.fsync(parent_fd)
        hook('parent_synced', stage)
        # Only specific files/directories created by this call, never rmtree.
        (stage/'INCOMPLETE').unlink()
        stage.rmdir()
    except (Exception, KeyboardInterrupt) as e:
        state = ('Published, but completion/durability is unconfirmed' if published else
                 'Publication may have succeeded' if rename_started else 'Export was not published')
        location = f' Incomplete staging: {stage}.' if stage else ''
        raise ExportError(f'{state}. Verify {dest} before retrying into a fresh name. '
                          f'Preserve your review.{location} Cause: {e}') from e
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
