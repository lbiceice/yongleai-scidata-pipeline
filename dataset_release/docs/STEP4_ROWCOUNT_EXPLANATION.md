# STEP4 Row-Count Explanation

The auxiliary STEP4 release contains two related but different public tables:

- `annotations/damage_consensus_s4.csv`: 7,455 rows
- `annotations/damage_by_engine_s4.csv`: 7,917 rows

These files should not be expected to have the same row count.

## Why the legacy `consensus` table has 7,455 rows

`damage_consensus_s4.csv` is a **patch-level release table**. It carries one released STEP4 record per patch across the same 7,455-patch corpus used in STEP3. The filename retains a legacy `consensus` label from the production workflow, but in this repository it should be interpreted as an auxiliary patch-level damage triage table.

## Why the engine-level table has 7,917 rows

`damage_by_engine_s4.csv` preserves **successful provider outputs** that survived parsing and canonicalization. In the current release:

- total rows: 7,917
- unique patch ids: 7,436
- patches with more than one successful provider output: 295

The observed engine counts are:

- `qwen`: 7,436 rows
- `claude`: 293 rows
- `gemini`: 188 rows

This means the engine-level STEP4 table is not a balanced four-engine panel. Instead, it is a retained-success table for the auxiliary pathology workflow.

## Why `protocol = openai_chat` appears in all rows

The `protocol` field records the canonical client/request schema family used by the archived transport layer. It does **not** identify the vendor behind the successful output. Vendor identity is carried in the `engine` column.

## How to interpret the auxiliary STEP4 layer

Because the engine-level STEP4 table reflects retained successful outputs rather than a complete balanced multi-engine panel, STEP4 should be interpreted as an **auxiliary triage layer**, not as a benchmark-grade pathology reference set.
