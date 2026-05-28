# Scientific Data Dataset Upload Preparation

## Prepared package
- Folder:
  `/Volumes/小满/YLMural-Dataset-v1.0/STEP8_summary/zenodo_package/YongleAI_SciData_repository_upload_20260412`
- ZIP upload artifact:
  `/Volumes/小满/YLMural-Dataset-v1.0/STEP8_summary/zenodo_package/YongleAI_SciData_repository_upload_20260412.zip`
- Pointer file:
  `/Volumes/小满/YLMural-Dataset-v1.0/STEP8_summary/zenodo_package/LATEST_UPLOAD_PACKAGE.txt`

## What is included
- STEP1 source manifest for 5 mural panoramas.
- STEP2 patch manifest for 7,455 patches.
- STEP3 public per-engine table (29,820 records) and consensus table (7,455 rows).
- STEP4 public damage consensus table (7,455 rows), sanitized per-engine table (7,917 rows), review-priority queue (373 rows), and sanitized manifest.
- Patch identifier crosswalk linking STEP2 filenames to STEP3 and STEP4 identifiers.
- Taxonomies, schema, prompts, engine configuration snapshots, summary statistics, and publication figures/tables.

## What was deliberately removed from the public package
- Source panoramas and patch PNG images.
- Local absolute filesystem paths.
- Private runtime traces and API endpoint details.
- Manuscript drafting files and internal submission-tracking files.
- STEP3 deployment-route fields and multiline raw-response payloads that were not necessary for public repository reuse.

## Current readiness
- The dataset upload package is ready for Zenodo deposition as the public annotation-and-metadata layer for a `Scientific Data` submission.
- The package is structured as a static, versioned release and includes `.zenodo.json`, `CITATION.cff`, `checksums_sha256.tsv`, and `UPLOAD_CONTENTS.tsv`.
- A ZIP artifact has already been generated for single-unit upload.
- For first-round submission, the immediate requirement is a seamless anonymous reviewer download route. The dataset DOI can be added later when the formal public repository record is published.

## Remaining external actions before journal submission is fully closed
1. Set up a seamless anonymous reviewer download route for first-round peer review.
2. Upload the ZIP or folder contents to Zenodo later and reserve the DOI.
3. Replace DOI-pending placeholders in the manuscript and repository metadata after DOI reservation.
4. Enable public or reviewer-authorized access to the GitHub code repository and archive the code with its own DOI.
5. Confirm the final rights route for patch-image dissemination so that the manuscript Data Availability statement exactly matches the public repository record.
