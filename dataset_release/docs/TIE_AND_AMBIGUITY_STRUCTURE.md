# Tie And Ambiguity Structure

This note summarizes how tie-bearing rows are represented in `annotations/consensus_labels_s3.csv`.

## Key distinction

The public table exposes two different concepts:

- `consensus_level`: vote concentration at the patch level;
- `consensus_status`: whether the released row is unambiguous or tie-resolved.

These fields should be interpreted together.

## Released counts

From `statistics/consensus_tie_validation_20260422.csv`:

- total patches: 7,455
- `high`: 497
- `medium`: 5,771
- `low`: 1,187
- `any_tie_flag = True`: 3,990
- tie-bearing rows in `high`: 0
- tie-bearing rows in `medium`: 2,803
- tie-bearing rows in `low`: 1,187
- `consensus_status = resolved_with_tie`: 3,990
- `consensus_status = resolved_no_tie`: 3,465

## Interpretation

Tie-bearing rows can still appear in `medium` because the public `consensus_level` rule is based on whether each dimension retains at least a two-vote top count, not on whether that top count is unique. Rows with `consensus_status = resolved_with_tie` should therefore be treated as ambiguity-exposed table-completion records rather than as unambiguous majority labels.

## Recommended use

- use `high` + `resolved_no_tie` for the lowest-noise subset;
- treat `resolved_with_tie` as disagreement-aware candidate labels;
- prioritize `low` for later manual adjudication.
