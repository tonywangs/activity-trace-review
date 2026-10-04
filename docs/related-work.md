# Related work and scope

Reviewed primary documentation during implementation on 2026-10-04:

- [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer) already provides local navigation through recorded test actions, screenshots, and other debugging evidence. Its [tracing API](https://playwright.dev/docs/api/class-tracing) documents capture options. This project borrows the useful action-plus-screenshot inspection pattern, but does not parse Playwright traces or capture browser activity.
- [LeRobotDataset v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3) documents a substantially broader multimodal dataset format with temporal data, video, and episode metadata. This project's bounded JSON/PNG format is not a replacement and has no demonstrated conversion compatibility.
- [Pillow rectangle drawing](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html#PIL.ImageDraw.ImageDraw.rectangle) uses inclusive rectangle endpoints. The exporter explicitly converts its half-open `[x,y,width,height]` format to `(x,y,x+width-1,y+height-1)`. The independent pixel oracle checks that boundary conversion.

The useful scope here is a small, offline, reproducible manual selection/redaction/export workflow with source-bound reviews and auditable output. No claim is made that trace viewers, demonstration segmentation, screenshot redaction, or deterministic dataset export are new. No recorder, model trainer, automatic sensitive-information classifier, or integration with the referenced formats is implemented.
