# Image And Inference Settings

This note summarizes the image-normalization and inference metadata that are archived in the public release.

## Source-image normalization

`metadata/import_manifest_step1.csv` records five normalized panorama identifiers (`raw001`–`raw005`) with widths from 19,220 to 29,400 pixels and a constant height of 7,511 pixels. These are institution-supplied panorama JPEGs that entered the archived workflow as already assembled source files rather than as raw capture frames. The import manifest also preserves:

- source checksum;
- estimated JPEG quality (`jpeg_quality_est`);
- thumbnail filename;
- normalized filename.

The release documents downstream normalization to sRGB and edge trimming, but the original capture-device settings, on-site lighting metadata, and any pre-import stitching notes remain with the protected institutional documentation corpus.

## Patch generation

Patch size and stride are archived in the STEP2 manifest:

- patch size: 512 × 512 pixels;
- stride: 358 pixels;
- overlap: approximately 30%.

`metadata/source_split_mapping.csv` provides the source-level split map and coordinate ranges for the resulting 7,455 patches.

## Inference preprocessing

The archived transport code in the reviewer package (`scripts/step3_4_transport.py`) records `thumbnail` mode as a Pillow `thumbnail()` resize with a **maximum side length of 256 pixels** before API transport. The public release therefore preserves the stable, release-stage preprocessing choice that was actually archived with the submission workflow.

The public package does not claim that vendor-side providers preserved those thumbnails without further internal resizing. It documents the archived client-side preprocessing and the release-table model strings used in the final tables.

## Release-table model strings and call window

The released per-engine table (`annotations/per_engine_labels_s3.csv`) records the following `model_name` values:

- `gpt-4o`
- `claude-sonnet-4-6`
- `gemini-2.5-flash`
- `qwen-vl-max-latest`

The corresponding call timestamps in the public table span:

- earliest: `2026-04-07T06:29:21.511274+00:00`
- latest: `2026-04-09T08:43:52.196913+00:00`

Archived configuration snapshots are preserved in `engine_configs/*.json`. One model string (`qwen-vl-max-latest`) is a provider alias rather than a fixed immutable vendor revision.
