# Validation evidence and limits

Run `.venv/bin/python scripts/verify.py` after preparing the dependencies documented in the README. The checked-in JSON reports and plain `results/tests.log` contain actual outputs; rerunning replaces timing measurements. No test result is inferred from a code review.

## What is independently checked

`tests/test_core.py` contains 240 deterministic randomized cases (seeds 0 through 239). Each constructs RGB images from seeded pixels, includes a known pixel-secret patch and PNG text metadata, creates actions with planted text secrets and source identifiers, selects inclusive intervals, removes actions, and replaces text. The oracle computes selection and half-open mask membership directly. It does not use exporter selection, rectangle drawing, or identifier helpers to calculate expected values.

For every exported case it checks:

- Exact retained action count, source order (including tied timestamps), timestamps, kinds, replacement text, and regenerated IDs/references.
- Every image pixel: black in the union of rectangles and exactly equal to the original normalized RGB pixel everywhere else.
- Every artifact name and encoded file for the planted text/source markers; image information dictionaries are empty. The independent validator also rejects ancillary PNG chunks.
- No unreferenced image or extra file, deterministic directory and ZIP replay, and unchanged input byte hashes.

This is not an OCR test, sensitive-information classifier, exhaustive fuzzer, or proof that an arbitrary screenshot is safe. The location and content of synthetic secrets are known in advance. Byte-string searches alone would not detect compressed or visually rendered secrets; the pixel oracle is the relevant evidence for the planted image region.

`activity_trace_review.validate` does not import the exporter or its schema helpers. It validates exported files without the source/review: manifest membership, hashes, integer sizes/counts, action schema/order, image reference sequence, PNG structure/metadata, and resource bounds. Its independence is at the implementation level, not an independent organization or security audit. Both image decoding paths use Pillow, so they share decoder risk.

## Failure and workflow coverage

Core checks exercise malformed/unsupported JSON, duplicate keys, unknown versions and fields, invalid IDs/references/order, mismatched source bindings, malformed/truncated PNGs, unsupported grayscale/animated PNGs, RGBA normalization, coordinate bounds and integer types, explicit screenshot/final-review gates, empty selections, path traversal, source symlinks and FIFOs, image/action/file/byte/pixel/export limits, cancellation, processing timeout, output collisions (including a simulated race), injected serialization/write/move failures, and cleanup after KeyboardInterrupt. Tests preserve source hashes.

The Chromium scenario drives actual file inputs, timeline/keyboard navigation, text editing without shortcut interference, segment editing, action removal, drag and numeric rectangles, shared screenshot review, mask-edit review invalidation, confirmation, keyboard save, review reload, invalid source/review rejection, cancelled downloads, export replay, and reopening. It checks the downloaded PNG pixels independently; after reopening, those pixels remain black even when there are no UI masks. Hostile HTML remains literal text. Special dictionary-key action IDs (`__proto__`, `constructor`) retain their replacements without modifying JavaScript prototypes. Unauthorized, foreign-Origin, and wrong-Host API requests are rejected.

The browser context blocks all requests except the exact loopback workbench origin and disables service workers. The result records attempted external requests and JavaScript errors. This is browser-request interception, not a machine firewall or an assertion about every possible Chromium background socket. No remote content is referenced by the application; the UI also has a restrictive Content Security Policy. Chromium is launched with background networking disabled.

The maximum-count browser fixture has 128 actions, 64 images of 512×512, and 16,777,216 decoded pixels. DOM counts are measured from the real page, with exactly one preview canvas. No synthetic measurement is substituted for a browser run.

The isolated example builds a wheel, creates a clean venv, installs from local wheels using `--no-index`, and invokes its installed CLI outside the checkout. It verifies the imported package resides in that venv. A verification-only `.pth` hook denies Python socket connection and DNS APIs, and a failing connection probe verifies the hook is active. The CLI generates the fixture, inspects hashes, creates an unconfirmed review, rejects unreviewed export, exports the synthetic example review, validates/reopens it, verifies replay, rejects a collision, and compares input hashes. The hook is not shipped in the application wheel. This establishes the exercised CLI workflow's independence from runtime network access, not OS-level confinement.

## Measurements and interpretation

`results/verification.json` records actual Python/platform/dependency versions, exit codes, elapsed times, and GNU time peak RSS for each verification command. RSS is the maximum resident memory of an individual measured process/child as reported by GNU time on Linux, **not the sum of all concurrent browser processes**. `results/browser.json` separately records the loopback server's own cumulative `ru_maxrss`, Chromium version, DOM counts, artifact sizes, and workflow results.

`results/benchmark.json` records seed 1307 on two 128-action workloads: 64 images at 512×512, and four images at 2,048×2,048. Both reach the total decoded-pixel cap. It measures import, PNG encoding without masks as a limited baseline, full bundle plus ZIP construction, deterministic replay, artifact hashes/sizes, and cumulative benchmark-process peak RSS. The encode-only baseline excludes validation, selection, manifest creation, and ZIP handling, so its runtime is not a like-for-like end-to-end comparison. One timed repetition per workload is recorded; there are no confidence intervals or throughput claims for real activity.

Measured runtimes vary with contention. A workload at the configured size cap can be rejected by the time cap on a slow machine. Native decoder execution can defer Python signal handling; the timer is not a kernel execution sandbox. The application does not promise a fixed process RSS limit or adversarial denial-of-service resistance.

## Remaining validation limits

Only synthetic data and Chromium on the recorded Linux environment have been exercised. There is no evidence yet for recorder interoperability, other browsers/operating systems, human usability or accessibility, human redaction accuracy, training utility, strong adversarial image handling, crash/power-loss recovery, or complete de-identification. The tool preserves timing and all explicitly retained content. Reviews and screenshots can still disclose information after a user marks them reviewed.

The browser screenshot in the README shows a synthetic workflow and contains planted marker strings in the **source review panel**. It is not an exported training artifact. Exported bundles are separately checked for exclusion of those planted strings and masked pixels.
