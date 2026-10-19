# Related work and scope

Reviewed primary documentation during implementation on 2026-10-04:

- [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer) already provides local navigation through recorded test actions, screenshots, and other debugging evidence. Its [tracing API](https://playwright.dev/docs/api/class-tracing) documents capture options. This project borrows the useful action-plus-screenshot inspection pattern, but does not parse Playwright trace archives. The bounded recorder added on 2026-10-19 uses Playwright browser events and screenshots.
- [LeRobotDataset v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3) documents a substantially broader multimodal dataset format with temporal data, video, and episode metadata. This project's bounded JSON/PNG format is not a replacement and has no demonstrated conversion compatibility.
- [Pillow rectangle drawing](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html#PIL.ImageDraw.ImageDraw.rectangle) uses inclusive rectangle endpoints. The exporter explicitly converts its half-open `[x,y,width,height]` format to `(x,y,x+width-1,y+height-1)`. The independent pixel oracle checks that boundary conversion.

The useful scope here is a small, offline, reproducible manual selection/redaction/export workflow with source-bound reviews and auditable output. No claim is made that trace viewers, demonstration segmentation, screenshot redaction, or deterministic dataset export are new. No general desktop recorder, model trainer, automatic sensitive-information classifier, or integration with the referenced formats is implemented.

## Bounded capture addition (2026-10-19)

- Playwright's [Python binding API](https://playwright.dev/python/docs/api/class-page#page-expose-binding) bridges the controlled page to the local recorder. [Locator screenshots](https://playwright.dev/python/docs/screenshots) capture only the task panel. This is an application-specific integration of existing capabilities, not a novel recording method.
- The task uses two small public factual inputs, paraphrased from [NASA Earth facts](https://science.nasa.gov/earth/facts/) (equatorial diameter 12,756 km) and [NASA Sun facts](https://science.nasa.gov/sun/facts/) (approximate diameter 1.4 million km). These facts were inspected during implementation and are bundled as text so capture needs no network. No NASA images or logos are used. The page identifies the original sources without enabling navigation during capture.
