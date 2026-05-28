# Technical Validation

## Workflow Alignment
- STEP4 vocabulary source: `DAMAGE_CATEGORIES / StepArchive.VOCAB` in the scientific workflow HTML.
- Export schema source: STEP4 `damage_consensus.csv + damage_by_engine.csv` schema in the scientific workflow HTML (the retained `consensus` filename is a legacy production name; in this repository it is treated as a patch-level triage table).
- Gate/QC/decision source: STEP4 `damageGate`, `assessDamageQuality`, and `damageDecision` logic in the scientific workflow HTML.

## Runtime Parameters
- sensitivity: `medium`
- engine execution mode: `parallel_batched`
- parallel engines: `2`
- provider order: `gemini, claude, openai, qwen`
- patch workers per engine: `6`
- channels: `6`
- minimum damage area: `25 px²`
- review confidence filter: `0.7`

## Validation Logic
1. Provider connectivity is checked before classification.
2. Providers are executed in controlled batches, with at most the configured number of parallel engines active at the same time.
3. Each provider output is parsed as JSON and canonicalized against the STEP4 controlled vocabulary.
4. Lesion-level results below the configured minimum area are filtered out.
5. Single-engine indexes, the refreshable live-progress index, and external-drive browse folders are updated during the run.
6. A patch-level triage record is formed from the retained successful providers and scored with reproduced gate/QC logic.
7. Literature support IDs are attached to each released patch-level triage record according to active categories.

## Current Outcome
- processed patches: `7455`
- accepted / review / rejected: `7063 / 373 / 19`
- connected providers: `4 / 4`
- guarded provider skips: `21793`

## Interpretation

This STEP4 layer is useful as an auxiliary triage signal, especially for routing patches into later review queues. It should not be interpreted as a balanced multi-engine pathology consensus benchmark.
