# Version 1 formats

All text is UTF-8 JSON. Unknown fields, duplicate object keys, malformed JSON, lone UTF-16 surrogates in text, unsupported versions, and non-finite numbers are rejected. Text is rendered with DOM text nodes and form values, never interpreted as HTML. The formats are deliberately small and are not a recorder interchange standard.

## Source directory

A directory contains exactly `trace.json` and all referenced PNGs. A valid exported directory can additionally contain `manifest.json`, which is independently validated. No extra files or subdirectories are accepted. Input symlinks and nonregular files are rejected. Screenshot references are plain basenames matching `[A-Za-z0-9_-]{1,64}.png`; URLs, absolute paths, slashes, and `..` traversal are not filenames.

```json
{
  "format": "activity-trace/1",
  "synthetic": true,
  "actions": [
    {
      "id": "step00",
      "timestamp_ms": 0,
      "kind": "type",
      "text": {"label": "Synthetic input", "value": "example", "url": ""},
      "screenshot": "screen0.png"
    }
  ]
}
```

Every action has exactly these five fields. IDs match `[A-Za-z0-9_-]{1,64}` and are unique within the source. They are stable references for reviews, not executable commands. `kind` is one of `observe`, `click`, `type`, `move`, `key`, or `wait`. These labels do not imply a supported recorder or action executor. `text` has zero or more of `label`, `value`, `url`, and `key`, each a string of at most 4,096 Unicode code points. Unknown text field names are rejected.

Timestamps are integer milliseconds in `[0, 2^53−1]`, monotonically nondecreasing. Equal timestamps are valid: array order breaks ties. The time origin is supplied by the dataset producer; exports preserve original timestamps without rebasing. Each action has exactly one screenshot reference, explicitly supplied by its producer. No interpolation, nearest-time inference, or implied before/after semantics is performed.

PNGs must be single-frame RGB or RGBA. They are verified and fully decoded under size limits. RGBA is composited over opaque white before preview and export; fully transparent hidden RGB is not retained. Grayscale, palette, animated PNG, other image formats, and unsupported color modes are rejected. Color profiles and ancillary metadata are discarded; there is no color-managed display guarantee. Pixel preservation means the normalized RGB raster, not metadata, original encoded bytes, or uncomposited RGBA channels.

## Review specification

```json
{
  "format": "activity-review/1",
  "source": "SHA256_OF_CANONICAL_SOURCE_HASH_MAP",
  "segments": [["step00", "step02"]],
  "removed": ["step01"],
  "replacements": {"step00": {"value": "[removed]"}},
  "screenshots": {
    "screen0.png": {"rects": [[16, 16, 240, 32]], "reviewed": true}
  },
  "confirmed": true
}
```

The binding digest is SHA-256 of a canonical JSON object mapping `trace.json` and every referenced PNG basename to the SHA-256 of its exact raw bytes. Canonical JSON uses sorted keys, compact separators, UTF-8 without ASCII escaping, and one trailing newline. The export manifest, when supplied, is validated but excluded from the binding. Reformatting the trace, changing a single input pixel, or renaming a referenced screenshot changes the binding. No filesystem paths are included. `inspect` exposes the binding and individual hashes for private provenance checks.

A segment is an inclusive `[first_action_id,last_action_id]` pair in source array order. Reversed or unknown endpoints are invalid. The union of all segments is taken, duplicate selections collapse, removed actions are subtracted, and retained actions appear once in source order. Zero segments are a valid draft; an empty selection cannot export. At most 128 segments are allowed.

Removal entries must be unique known IDs. Replacements can only target existing text fields on known IDs. Empty strings are valid replacements. Edits on an action outside the final selection are valid but contribute nothing to its export.

Each rectangle is `[x,y,width,height]` in **normalized source-image pixels**, origin top-left, x rightward, y downward. All values must be integers, x/y nonnegative, width/height positive, and the full rectangle inside the image. Coverage is half-open: `x <= pixel_x < x+width`, `y <= pixel_y < y+height`. The exporter writes `(0,0,0)` for every covered pixel. Overlapping rectangles form an opaque union; no blur or transparency is used. Each image allows at most 128 rectangles.

Screenshot review and rectangles are keyed by source screenshot basename. Shared references therefore share masks and one explicit review decision. The UI clears that decision whenever masks are edited and clears final confirmation when edits or selection change. Each retained screenshot must have `reviewed: true`, even if it has no masks. Nonretained screenshots need not be reviewed. `confirmed: true` is also required for retained text and selection. A specification is a user's declaration; no cryptographic proof of human attention is possible, and manually editing it can assert review.

Save/load validates the entire specification before replacing current work. A mismatched source, bad reference, bad coordinate, unsupported version, or malformed specification leaves the active review unchanged. Saved review files contain source identifiers and may contain sensitive replacement text; they never belong in the shared export.

## Exported directory / ZIP

A bundle contains exactly:

- `trace.json`: the selected actions in the source schema, with replacements applied and IDs `action0001`, `action0002`, etc.
- `image0001.png`, etc.: regenerated RGB PNGs, assigned in order of first retained reference. Every image is reencoded even when it has zero masks. Only IHDR, IDAT, and IEND chunks are allowed.
- `manifest.json`: `format: "activity-bundle/1"`, integer action/image counts, and a `files` object mapping each trace/image filename to its exact `bytes` and `sha256`. The manifest does not list or hash itself.

The synthetic flag is preserved. Source action IDs, source screenshot names, source paths, hashes of source data, redaction coordinates, review declarations, arbitrary metadata, thumbnails, and original PNG payloads are not copied into export structure. A fresh allowlist is constructed; nothing is exported by copying an input directory.

ZIP entries are sorted, stored without ZIP compression, have a fixed 1980 timestamp and fixed permission attributes, and contain no directory prefixes. Repeat exports from the same source/review with the pinned runtime produce identical file and ZIP bytes. Byte identity across Pillow/zlib/Python versions or platforms is not promised. IDs identify positions in an exported bundle, not global content identity.

The independent validator checks file membership, hashes, sizes, schema, action IDs and ordering, image references, PNG chunk allowlists, and dimensions. It cannot infer whether sensitive content remains. It does not need the source or review. The seeded tests add separate source-aware text and per-pixel oracles.

## Resource and failure bounds

| Resource | Limit |
| --- | ---: |
| Input bytes, including optional manifest | 24 MiB |
| Input files | 66 |
| Actions | 128 |
| Referenced images | 64 |
| JSON document | 512 KiB |
| Encoded PNG | 8 MiB |
| Image side | 2,048 pixels |
| Pixels per image | 4,194,304 |
| Total decoded image pixels | 16,777,216 |
| Each text value | 4,096 Unicode code points |
| Segments / rectangles per image | 128 / 128 |
| HTTP JSON/base64 envelope | 34 MiB |
| Export directory | 24 MiB effective, to remain reimportable |
| ZIP archive | 32 MiB |
| CLI operation / HTTP request processing | 10 seconds |
| Socket idle timeout | 15 seconds |

Output JSON and each reencoded image must also meet the corresponding input limits. Replacements may expand a tiny input beyond the JSON limit; export then fails rather than creating an unreadable bundle. Limits bound data sizes rather than promising a fixed resident memory limit. Pillow uses more than three bytes per RGB pixel internally and operations allocate temporary copies. Measured RSS is documented separately.

The POSIX timer bounds request reads and processing with Python exception delivery. C extension code can defer Python signal handling until it returns; dimensions and encoded-byte limits also bound native decode/encode work. This is not a kernel CPU/memory sandbox or a precise preemption guarantee for hostile native decoder code. Direct library calls use cooperative budget checks; the CLI and HTTP server add the timer.

CLI directory output is staged in a private sibling directory, reserves a fresh destination exclusively, then moves files into it. Collision, cancellation, serialization failure before staging, and injected write/move failures are tested. Handled failures remove the destination owned by that operation and its staging directory. Publication is not crash-atomic; forced process termination can leave staged or partial files. Existing destinations are never overwritten. No success is printed before completion.
