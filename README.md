# Public Code Release Candidate (Scientific Data)

This package is the public-code-release candidate derived from the frozen reviewer code snapshot prepared for the Yongle Palace mural Data Descriptor workflow.

It contains the scripts, configuration files, dependency specification, and selected technical notes needed to inspect the release-building and validation workflow without requiring direct access to the original live working repository.

## Current publication status

Local metadata was aligned on 2026-05-23 with the PaperSpine M3 manuscript package. The intended public software release version is `v1.0.0`, and the software title is:

`YongleAI public code release: multi-engine candidate-annotation and validation pipeline for Yongle Palace Taoist mural image patches`

The package is public at `https://github.com/lbiceice/yongleai-scidata-pipeline` with release tag `v1.0.0`. The GitHub release has been published; the DOI-backed Zenodo software archive remains the remaining external closure item until Zenodo exposes the software DOI.

Companion dataset DOI: [`10.5281/zenodo.19718760`](https://doi.org/10.5281/zenodo.19718760).

## Included

- `scripts/`: selected Python scripts used for STEP2 tiling, STEP3/STEP4 transport, release assembly, and validation.
- `configs/`: selected static configuration and prompt files referenced by the workflow.
- `dataset_release/requirements.txt`: dependency specification used for the release environment.
- `environment.yml`: conda-style environment candidate derived from `dataset_release/requirements.txt`.
- `LICENSE`: MIT license for the code in this software release candidate.
- `CITATION.cff`: citation metadata for the future public software release.
- `.zenodo.json`: Zenodo metadata candidate for the future public software release.
- `CODE_PUBLIC_RELEASE_PRECHECK_20260423.md`: compact readiness note separating completed local packaging work from still-open publication actions.
- `MINIMAL_REPRODUCTION_WORKFLOW.md`: reviewer-oriented guide to inspect release assembly and validation logic.
- `CODE_RELEASE_METADATA_20260423.json`: frozen snapshot metadata, commit hash, and internal submission-stage version tag.
- `PUBLIC_CODE_RELEASE_STATUS_20260423.md`: public-release candidate status note and remaining closure blockers.

## Setup: API keys, engine endpoints, and paths

**API keys (never distributed).** Each annotation engine reads its key from an environment
variable: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (OpenAI-compatible engines)
and `DASHSCOPE_API_KEY` (Qwen). Set these in your shell before running. The optional
`configs/step4_config.yaml: api_keys_path` may point to a local plain-text key file (one key per
line); it defaults to `./api_keys.txt` and must be supplied by you. No keys are included here.

**Engine endpoints (transparency).** As recorded in `scripts/step3_4_transport.py` and the
transport lock, GPT-4o, Gemini, and Claude were accessed through the **OpenAI-compatible
`api.gptsapi.net` proxy**, and Qwen through the official **Alibaba DashScope** endpoint
(`dashscope.aliyuncs.com/compatible-mode`). These `base_url` values are retained as-is for
transparency and because the transport-lock validation depends on them; to re-run against
official vendor endpoints instead, edit the `base_urls` in `configs/` and the lock files
accordingly.

**Machine-specific paths.** Some `configs/*.yaml` and scripts contain absolute paths from the
original workstation (e.g. data roots, model-weight checkpoints). Treat these as examples and
point them at your own locations (e.g. set `WEIGHTS_DIR` for SAM checkpoints and your own data
root) before running.

## Not included

- API credentials
- local runtime logs
- caches and compiled artifacts
- large intermediate outputs
- the `.git` directory
- a DOI-backed software record, until Zenodo completes GitHub-release archiving

## Use

Readers should start with `PUBLIC_CODE_RELEASE_STATUS_20260423.md` and `MINIMAL_REPRODUCTION_WORKFLOW.md`, then inspect the referenced scripts together with `checksums_sha256.tsv`, `File_Inventory.csv`, `PACKAGE_SUMMARY.json`, and `CODE_RELEASE_METADATA_20260423.json`. The underlying frozen submission-stage snapshot is versioned internally as `v1.0.0-submission-review`. The public repository URL and `v1.0.0` tag are now available; the remaining external closure item is the DOI-backed Zenodo software archive.
