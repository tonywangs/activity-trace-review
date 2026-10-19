# Bounded, consented browser capture

`activity-trace record FRESH_DIRECTORY` launches a new nonpersistent Chromium context and the bundled local Space fact notebook. It also starts the normal token-protected loopback workbench. No existing browser profile, cookies, account, extension, or personal dataset is loaded. The recorder process blocks browser HTTP requests outside its local workbench origin and blocks service workers. This is application-level request filtering, not a machine-wide network sandbox or a claim that Chromium never performs internal networking.

The task is deliberately small but real: a participant chooses public Earth/Sun facts, keeps a fact, and commits a note. Screenshots come from the live browser, not generated fixture images. Browser automation is used for the saved demonstration and regression checks; the interactive command uses the same session implementation in a visible browser. A graphical desktop is required for the interactive command. The supported capture viewport is the launched 1000×900 (or larger) layout. Each snapshot resets page scroll and briefly locks it so consent controls do not overlay the captured panel; capture fails closed if resizing/zooming makes the viewport smaller. Sticky controls keep Stop visible when scrolling between captures. This environment's verification is headless; unaided human interaction has not been tested.

## Consent and timing

A fresh page is OFF. Start is disabled until the participant checks the explicit consent box. The Python recorder also checks the checkbox before enabling capture. While recording, the red bordered status panel remains above the task surface. Start/stop/consent controls are outside the captured region. There is one recording per process session; relaunch into a fresh destination for another.

Only trusted DOM clicks on the four bundled task buttons create events. Earth and Sun change the displayed fact; Keep fact copies it into the notebook; Commit note records the current note value with kind `type`. Keyboard activation of a task button also produces its ordinary click event. Typing, focus, hovering, scrolling, selecting text, clipboard contents, individual keys, arbitrary navigation, and actions outside the panel are not separate events. This is not a general browser or desktop recorder.

Each accepted event has a timestamp in elapsed integer milliseconds from Start, the button's fixed label, its resulting value, and a 900×420 screenshot of the panel after its synchronous update. The surface becomes inert until capture finishes to preserve action/screenshot ordering. Capture is limited to 16 actions and five minutes; it uses at most 6,048,000 decoded screenshot pixels. These fit within the reviewer's normal limits. A timer stops the page at five minutes; the backend independently rejects events after that elapsed limit. The recorded timestamp is receipt time in the backend, not a hardware input timestamp.

Stop immediately clears the page's capture flag and revokes backend capture. Any screenshot still in flight is discarded, so the last visibly performed action can be absent when Stop interrupts it. Stop waits for that pending operation before saving accepted events. Post-stop task interactions still work but generate no data. Closing/navigating/reloading the capture page before Stop does not save the in-memory recording. Ctrl+C closes the browser/server. A saved raw source survives process exit and can be reopened with `activity-trace serve DIRECTORY`.

## Privacy and persistence

Screenshots include **everything visible in the task panel**, including uncommitted note text and previously committed text. Do not enter personal secrets. The visible indicator is consent UI, not a cryptographic record of who consented. Participants must consent themselves when a person operates the recorder; the automated test exercises its own test-only session.

The stop operation creates a fresh mode-0700 raw-source directory, validates its format, and imports it into the workbench. Existing destinations are rejected. Raw saving is not the transactional reviewed-bundle export: interruption or disk errors can leave an incomplete private source directory. If saving/import fails, capture remains off; inspect that directory and reopen it if complete. No automatic retry overwrites data. A stop with zero accepted actions creates no source and offers no review link. Raw files, source-bound review files, and downloaded ZIPs are not encrypted.

Review and export never happen automatically. Choose segments, replace sensitive retained text, mask screenshot regions, and explicitly review each retained image and the final selection. The exported bundle has no consent/control records; retain any needed consent evidence separately and privately. Integrity validation does not prove adequate redaction, authenticity, human participation, or training value. The `synthetic: false` source flag denotes captured browser events rather than a constructed trace; automation can produce captured events too.

## Reproducing the demonstration

After installing the optional capture dependency and Chromium as described in the README:

```sh
.venv/bin/python tests/capture_flow.py
.venv/bin/activity-trace serve results/capture/source
.venv/bin/activity-trace verify results/capture/bundle
```

The test operates actual browser controls, records five actions, selects the middle three, replaces a test-only marker, masks the entire notes column in the sensitive screenshot, and exports through the review UI. The independent oracle checks the exact retained values, original timestamp subset, bundle inventory, excluded marker bytes, and every output pixel against the expected original-or-black value. It also checks no pre-consent/post-stop event capture, unchanged source files after Stop, rejection of untrusted DOM events, the count limit, the five-minute timer with a controlled browser clock, the independent backend elapsed-time guard, the visible Stop control after scrolling, and stopping during a delayed screenshot. Saved screenshot artifacts let a reviewer inspect the indicator and redaction. Files in `results/capture/source` are safe demonstration data only, never personal recordings.
