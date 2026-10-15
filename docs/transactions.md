# Transactional export contract

Export retains the existing activity-bundle/1 format and review semantics. Empty
selections remain errors. The publication boundary is a whole directory rename,
not the creation of a manifest or a browser download event.

## Guarantees and assumptions

Supported publication requires Linux, libc `renameat2`, and a filesystem that
implements `RENAME_NOREPLACE`, regular-file fsync, and directory fsync. There is
no replace/exists-check fallback. Unsupported systems fail closed. Use a local
filesystem and a parent directory controlled by the current user. Concurrent
writers may choose the same destination; exactly one succeeds. Malicious local
processes able to modify the parent or staging directory are outside the model.
Network filesystems (including NFS's ambiguous failure semantics) are unsupported.

The destination parent must already exist. Export creates a random, mode-0700
`.trace-stage-*` sibling containing an `INCOMPLETE` marker and a `payload`
subdirectory. Only the already redacted records and reencoded RGB PNGs enter
this directory. Source files, review specifications, removed text, and original
screenshots are never copied by the export writer. Each payload file is mode
0600, flushed and fsynced. The separate validator rereads the payload, checks its
inventory, records, hashes, PNG structure and decoded pixels, then the payload
directory is fsynced. A single renameat2 with RENAME_NOREPLACE publishes payload
under the requested name. Parent fsync follows. Staging paths are never accepted
as published bundles, even if their payload is structurally complete.

Before rename, interruption leaves the destination absent. After rename, the
destination contains the whole validated bundle. No existing destination (file,
directory, or symlink) is replaced. Exceptions and SIGKILL do not trigger deletion
of destinations. Owned staging is deliberately retained on failure for inspection;
no automatic recursive deletion of unrelated directories is attempted. Successful
exports remove their own empty staging wrapper. The guarantee concerns process
interruption and atomic visibility, not immunity to subsequent modification.

A failure or lost response after rename is ambiguous to the caller: publication
may already have succeeded. A parent-fsync failure reports publication with
unconfirmed durability, never rolls it back. File/directory fsync improves crash
durability but hardware, mount options, filesystem bugs, and power loss have not
been tested. Do not infer power-loss survival from SIGKILL tests.

## Recovery

Keep the unchanged source and save the source-bound review privately. After any
error or interruption, run `activity-trace verify DESTINATION`. If valid, inspect
and use that bundle; do not retry into it. If absent, retry into a fresh name. If
invalid or unexpected, preserve it for inspection and choose a different name.
List `.trace-stage-*` siblings including hidden entries. Each is incomplete and
must never be imported or shared as a completed export. After ensuring no exporter
is using it, inspect and manually remove only the specific staging directory you
own. The application never resumes or promotes leftover staging.

Browser exports publish to the server's `--export-root` (default `reviewed-exports`
in its working directory). A user-chosen simple destination name lets a lost
response be reconciled on disk. The browser reports publication only after the
server returns success, then requests a convenience ZIP download. It cannot
confirm that the browser saved that ZIP. Cancelling transport does not undo a
server publication; verify the named destination before retrying. Review edits
remain available after an error; save them before closing the page.

`activity-trace verify` (also `validate`) checks internal integrity offline, not
adequacy of redaction or authenticity. Hashes are unkeyed and can be recomputed by
an attacker. The original format carries no signed identity or source proof.

## Primary references and prior implementations

The Linux [rename(2) documentation](https://man7.org/linux/man-pages/man2/rename.2.html)
defines atomic rename and the no-replace flag, filesystem support, and NFS
failure ambiguity. [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
explains the separate directory flush needed for directory entries. Python's
[os documentation](https://docs.python.org/3/library/os.html#os.rename) documents
that rename can replace an empty destination directory on Unix; a preliminary
exists check is therefore insufficient. This uses established filesystem
primitives and makes no novelty claim.

The existing [python-atomicwrites implementation](https://github.com/untitaker/python-atomicwrites/blob/master/atomicwrites/__init__.py)
uses fsync plus link/unlink for Unix no-overwrite file publication. That is a
useful file-level precedent, but hard-link publication cannot publish our whole
directory. This project therefore uses Linux's explicit directory-capable
no-replace rename, without importing that dependency.
