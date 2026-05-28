# Minimal Reproduction Workflow

This note gives editors and reviewers the smallest practical route through the frozen code snapshot shipped with the submission. It is not intended to recreate live commercial-API calls. Instead, it shows how to inspect the release-building, validation, and transport logic that produced the deposited annotation-and-metadata package.

## 1. Verify package integrity

1. Confirm that `checksums_sha256.tsv` and `PACKAGE_SUMMARY.json` are present at the package root.
2. Review `dataset_release/requirements.txt` for the archived Python environment.
3. Inspect `dataset_release/docs/consensus_algorithm.md` and `dataset_release/docs/data_dictionary.md` before reading the scripts, so the field names and tie-handling conventions are clear.

## 2. Inspect tiling and manifest logic

Read these scripts in order:

1. `scripts/step2_tiling.py`
2. `scripts/step2_rebuild_manifest.py`

These files show how panorama-level inputs were converted into 512 x 512 patch manifests, how overlap was controlled, and how STEP2 identifiers were stabilized before later stages.

## 3. Inspect transport and batch execution logic

Read these scripts in order:

1. `scripts/step3_4_stage1_freeze.py`
2. `scripts/step3_4_stage2_build_pilot_set.py`
3. `scripts/step3_4_run_pilot.py`
4. `scripts/step3_4_transport.py`
5. `scripts/run_full_batch.py`

Together they document how pilot calibration, transport settings, thumbnail resizing, retry behaviour, and final multi-engine execution were orchestrated. In particular, `step3_4_transport.py` contains the archived thumbnail path used during submission-stage transport.

## 4. Inspect release assembly and validation logic

Read these scripts in order:

1. `scripts/build_scientific_data_release.py`
2. `scripts/validate_release.py`
3. `scripts/engine_completion_check.py`
4. `scripts/step4_engine_check.py`
5. `scripts/step4_label_validator.py`

These scripts show how the static release package was assembled, how required files were checked, and how STEP4 outputs were normalized and verified.

## 5. Inspect comparison and smoke utilities

The following files document the smaller-scale control and smoke workflows referenced in the manuscript and support packages:

1. `scripts/run_smoke10.py`
2. `scripts/qc_smoke10.py`
3. `scripts/step3_ab_test.py`
4. `scripts/step3_ab_200.py`

They are provided to show how smaller diagnostic subsets were prepared and checked, not as a claim that the public release can be re-generated end-to-end without licensed API access.

## 6. What this package does and does not reproduce

This snapshot is sufficient to inspect:

- release structure
- taxonomy enforcement
- tie-handling logic
- thumbnail preprocessing settings
- validation checkpoints
- release-integrity checks

This snapshot does not by itself reproduce:

- the protected panorama corpus
- the restricted patch-image layer
- live commercial inference calls
- private credentials or local working directories

For those components, reviewers should consult the deposited annotation-and-metadata package together with `docs/RIGHTS_AND_ACCESS.md` and the reviewer-support materials supplied through the submission route.
