# Consensus Algorithm And Tie Handling

The STEP3 consensus table is a **rule-based summary layer** derived from `annotations/per_engine_labels_s3.csv`.

## Dimension-level rule

For each patch and each HSGF dimension (D1–D5):

1. collect the non-empty engine labels;
2. count label frequencies;
3. select the most frequent value as the released table value;
4. record agreement counts, total valid votes, and tie metadata.

`N/A` is retained as a valid released value for non-applicable D2 and D3 cases.

## Consensus-level rule used in the released table

In the public release, `consensus_level` is derived from the **dimension-level top-vote count**, not from chance-corrected reliability:

- `high`: every dimension has a top-vote count of 4 (4/4 agreement across all five dimensions);
- `medium`: every dimension has a top-vote count of at least 2, but at least one dimension is not unanimous;
- `low`: at least one dimension has a top-vote count of 1.

`consensus_level` is therefore a **within-patch vote-concentration indicator**, not a chance-corrected reliability statistic.

## Tie handling

Some patches contain tied top vote counts within one or more dimensions. For backward compatibility, the public table retains the resolved value already written to the consensus columns, but it now also exposes:

- `D*_tie_flag`
- `D*_top_vote_count`
- `D*_num_valid_votes`
- `D*_candidate_values`
- `any_tie_flag`
- `tie_dimensions`
- `consensus_status`

Rows with `consensus_status = resolved_with_tie` should be interpreted as **table-completion values**, not as adjudicated truth.

Tie-bearing rows can appear in:

- `medium`, when every dimension still retains at least a two-vote top count; or
- `low`, when one or more dimensions have only a single-vote top count.

## Observed tie frequency in the public release

`statistics/consensus_tie_summary.csv` reports the patch counts affected by ties:

- D1: 895 patches
- D2: 1,383 patches
- D3: 806 patches
- D4: 1,707 patches
- D5: 1,367 patches
- any dimension: 3,990 patches

`statistics/consensus_tie_validation_20260422.csv` further reports the cross-tabulated release counts:

- total patches: 7,455
- high: 497
- medium: 5,771
- low: 1,187
- tie-bearing rows in any dimension: 3,990
- tie-bearing rows classified as `medium`: 2,803
- tie-bearing rows classified as `low`: 1,187

These values are included so that downstream users can filter or re-review ambiguous consensus rows explicitly.
