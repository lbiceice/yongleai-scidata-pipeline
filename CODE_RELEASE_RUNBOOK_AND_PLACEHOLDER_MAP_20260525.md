# Code Release Runbook & Placeholder-Closure Map

Prepared: 2026-05-25 · For: YongleAI Scientific Data Data Descriptor (v1) Code Availability blocker.

This package is **locally release-ready** (MIT LICENSE, README, CITATION.cff, .zenodo.json,
environment.yml, requirements.txt, configs, scripts, checksums, file inventory all present).
Only three **external** actions remain: a public GitHub URL, a `v1.0.0` release tag, and a
Zenodo software DOI. This runbook is the ordered path to close them and then propagate the
URL/DOI everywhere it is referenced.

---

## STEP 0 — Pre-publish sanitization (DO THIS BEFORE PUSHING)

A secret scan on 2026-05-25 found **no hardcoded API keys** (all engines read env vars:
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `DASHSCOPE_API_KEY`; no `.env`/`.key`/
credential files). But three items must be cleaned before the repo is public, committed as a
dedicated **"public-release sanitization"** commit (so the public tag differs from the frozen
reviewer commit `85269cc5b52cc59fe8112ba6b76bc93ebae7492b`, which stays cited as the reviewer snapshot):

| # | Location | Issue | Status (2026-05-25) |
|---|---|---|---|
| 1 | `configs/step4_config.yaml` `api_keys_path` | Formerly pointed to a machine-local key-file path containing a local username | **DONE** — replaced with `./api_keys.txt` + comment (value is not consumed by any shipped script; env-var route documented in README). |
| 2 | `base_url: "https://api.gptsapi.net/v1"` (in `configs/step3_4_run_lock.yaml`, `configs/step3_4_transport_lock.yaml`, `configs/step4_engine_config.yaml`, `configs/step4_config.yaml`, `scripts/step3_4_transport.py`) | Discloses a third-party API proxy (gptsapi.net) for GPT-4o/Gemini/Claude | **KEPT (transparent), NOT genericized** — the code already labels these `"source": "gptsapi.net proxy"` and `_validate_base_url`/transport-lock **validates against these exact URLs**, so replacing them with `${ENV}` would break the lock. Handled by a transparent README "Setup: API keys, engine endpoints, and paths" section. Qwen/DashScope is the official Alibaba endpoint. Optionally mirror this disclosure in Methods. |
| 3 | Machine-absolute paths | One user-home cache path formerly leaked a local username; `/Volumes/小满/...` appears ~18× across configs+scripts | **PARTIAL** — the one username-bearing path (`configs/model_versions.yaml` SAM checkpoint) → `${WEIGHTS_DIR}/...`. The `/Volumes/小满/...` paths (drive-name only, not username; some are default constants in scripts) are **documented as "set your own paths" in the README** rather than mass-edited, to avoid breaking the frozen pipeline. Optional: genericize them when you wire up `${DATA_ROOT}` in your repo. |

Secret re-scan after these edits: **no hardcoded keys, no username leak** remaining in configs. Commit as e.g. `chore: public-release sanitization (v1.0.0)`.

---

## STEP 1 — Create the public GitHub repository

1. New repo, e.g. `yongleai-scidata-pipeline` (public). Suggested description: *"Multi-engine
   candidate-annotation and validation pipeline for Yongle Palace Taoist mural image patches
   (Scientific Data Data Descriptor)."*
2. Push the **contents of this directory** (`当前代码公开候选包_目录_20260423/`) to the repo root.
   README.md, LICENSE (MIT), CITATION.cff, .zenodo.json are already at the top level — GitHub will
   render them automatically.
3. Confirm README renders, LICENSE is detected as MIT, and "Cite this repository" appears (from CITATION.cff).

## STEP 2 — Mint the software DOI via Zenodo–GitHub integration

1. Log in to https://zenodo.org → **Account → GitHub** → flip the toggle **ON** for the new repo
   (this must be done BEFORE creating the release).
2. On GitHub, **Releases → Draft a new release** → tag = `v1.0.0`, title = `v1.0.0`, target = the
   sanitized commit. Publish the release.
3. Zenodo auto-creates a software record and mints a **software DOI** (a concept DOI +
   a version DOI). Use the **version DOI** for `v1.0.0` in the citation; the concept DOI is the
   "all versions" DOI.
4. On the Zenodo record, confirm metadata (it ingests `.zenodo.json`): title, MIT license,
   author/ORCID, and the `isSupplementTo` link to the dataset DOI. Edit if needed; do not delete
   the dataset cross-link.

You now have: **GitHub URL**, **tag `v1.0.0`**, **software DOI**. Close the placeholders below.

---

## STEP 3 — Placeholder-closure map (replace everywhere, once)

Replace `https://github.com/lbiceice/yongleai-scidata-pipeline`, `v1.0.0` (= `v1.0.0`), `<Zenodo software DOI after archive>`:

**A. Former placeholder tokens**
- `04_CODE_AND_REPRODUCTION/当前代码公开候选包_目录_20260423/CITATION.cff` (this package — ship this file)
- same dir `.zenodo.json` (prose note about pending placeholders)
- `…/PaperSpine_M3_final_paper_20260522/citation_cff_patch_20260522.cff` (PaperSpine source — optional)
- `…/PaperSpine_M3_translation_zh_20260522/citation_cff_patch_zh.md` (PaperSpine source — optional)
- redundant: `CITATION_PATCH_PAPERSPINE_M3_20260522.cff` in this dir is already applied to `CITATION.cff`; it can be deleted to avoid confusion.

**B. Prose "external closure item" in the manuscript & cover letters (these gate submission)**
- `01_MANUSCRIPT_latest_with_figures/manuscript_image_public_current_20260428.md` — **Code Availability** section (replace the "remain external closure items…" sentence with the final statement in STEP 4). **Then regenerate `_WITH_FIGURES_20260525.docx`** via pandoc.
- `…_ZH_PAPERSPINE_M3_20260523.md` — same (ZH), then regenerate ZH docx.
- `07_ADMIN_SUBMISSION_TO_PREPARE/COVER_LETTER_FINAL_FILLED_SCIENTIFIC_DATA_PAPERSPINE_M3_20260522.md` and the DRAFT cover letter.
- Gate docs (`AUTHOR_DECLARATIONS_…`, `EDITORIAL_POLICY_…`) — flip Code Availability from BLOCKED to READY.

**C. Dataset-side (only if you also want the software DOI cross-linked from the dataset record)**
- Optionally add a `references`/related-identifier `isSupplementedBy [software DOI]` on the Zenodo **dataset** record after both DOIs exist.

---

## STEP 4 — Paste-ready Code Availability statement (final form)

Replace the manuscript Code Availability section's closure sentence with (fill the two values):

> All workflow scripts, configuration files, prompt specifications, the dependency
> specification, and the validation pipeline used to build and verify this dataset are openly
> available at GITHUB_URL under the MIT License, archived at Zenodo under DOI SOFTWARE_DOI
> (release `v1.0.0`). The reviewer-stage frozen snapshot corresponds to Git commit
> `85269cc5b52cc59fe8112ba6b76bc93ebae7492b`. Commercial vision-language models were accessed
> as external annotation engines through their respective APIs; API keys are supplied by the
> user via environment variables and are not distributed with the code.

(If you keep the gptsapi.net proxy, add one transparent sentence: *"GPT-4o, Gemini, and Claude
were accessed via the OpenAI-compatible gptsapi.net proxy; Qwen via Alibaba DashScope."*)

---

## STEP 5 — Final consistency check before submission

- [ ] STEP 0 sanitization committed; secret re-scan clean.
- [ ] GitHub public, README/LICENSE/CITATION render.
- [ ] `v1.0.0` tag + software DOI resolve (test `curl -sI https://doi.org/<software_doi>` → 302).
- [ ] All placeholder tokens replaced (grep the package returns nothing).
- [ ] Manuscript EN+ZH Code Availability updated; `_WITH_FIGURES_20260525.docx` regenerated.
- [ ] Gate docs Code Availability = READY.
- [ ] Dataset DOI also published (separate blocker) and consistent.
