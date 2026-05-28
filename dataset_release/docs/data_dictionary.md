# Data Dictionary


## consensus_labels_s3.csv

| Field | Type | Description |
|---|---|---|
| `patch_id` | string | Unique patch identifier (yl_raw_{wall}_{row}_{col}) |
| `n_engines` | string | Number of engines that annotated this patch (integer, typically 4) |
| `split` | string | Data partition assignment (train / val / test) |
| `D1` | string | Iconographic role consensus label (10 categories) |
| `D1_agreement` | string | Number of engines agreeing on D1 consensus (1-4) |
| `D1_total` | string | Total engines that provided D1 label |
| `D2` | string | Headgear type consensus label (18 categories or N/A) |
| `D2_agreement` | string | Number of engines agreeing on D2 consensus |
| `D2_total` | string | Total engines that provided D2 label |
| `D3` | string | Held object consensus label (14 categories or N/A) |
| `D3_agreement` | string | Number of engines agreeing on D3 consensus |
| `D3_total` | string | Total engines that provided D3 label |
| `D4` | string | Damage condition consensus label (5 levels) |
| `D4_agreement` | string | Number of engines agreeing on D4 consensus |
| `D4_total` | string | Total engines that provided D4 label |
| `D5` | string | Spatial position consensus label (4 zones) |
| `D5_agreement` | string | Number of engines agreeing on D5 consensus |
| `D5_total` | string | Total engines that provided D5 label |
| `consensus` | string | Overall consensus category string |
| `consensus_level` | string | Patch-level vote concentration indicator (high / medium / low), not a direct label-validity score |
| `consensus_count` | string | Number of dimensions with >= 2/4 agreement |
| `consensus_engines` | string | Number of engines contributing to consensus |

## per_engine_labels_s3.csv

| Field | Type | Description |
|---|---|---|
| `patch_id` | string | Unique patch identifier (yl_raw_{wall}_{row}_{col}) |
| `stratum` | string | [stratum] |
| `split` | string | Data partition assignment (train / val / test) |
| `contract_mode` | string | [contract_mode] |
| `engine` | string | Engine identifier (openai / claude / qwen / gemini) |
| `model_name` | string | [model_name] |
| `provider` | string | [provider] |
| `image_mode` | string | [image_mode] |
| `image_size_bytes` | string | [image_size_bytes] |
| `raw_response` | string | [raw_response] |
| `parsed_json` | string | [parsed_json] |
| `normalized_json` | string | [normalized_json] |
| `D1` | string | Iconographic role consensus label (10 categories) |
| `D2` | string | Headgear type consensus label (18 categories or N/A) |
| `D3` | string | Held object consensus label (14 categories or N/A) |
| `D4` | string | Damage condition consensus label (5 levels) |
| `D5` | string | Spatial position consensus label (4 zones) |
| `raw_valid` | string | [raw_valid] |
| `raw_schema_ok` | string | [raw_schema_ok] |
| `raw_vocab_ok` | string | [raw_vocab_ok] |
| `raw_errors` | string | [raw_errors] |
| `normalized_valid` | string | [normalized_valid] |
| `cross_dim_warnings` | string | [cross_dim_warnings] |
| `fallback_reason` | string | [fallback_reason] |
| `gate_pass` | string | [gate_pass] |
| `review_required` | string | [review_required] |
| `latency_ms` | string | [latency_ms] |
| `timestamp` | string | [timestamp] |
