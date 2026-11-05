# PAACC Golden Dataset (real-document regression benchmark)

Independently verified expected results for real documents, used to measure the PDF → analysis → BOQ pipeline
and to detect regressions. **The data itself is confidential and is not stored in this repository**: this folder holds
only the structure. Files placed in `drawings/`, `expected/`, `manifests/` and `results/` are ignored by git
(see `.gitignore`).

## Layout
| Folder | Content | In git? |
|---|---|---|
| `drawings/` | the original PDFs (byte-identical; never modified) | no |
| `manifests/` | one `<sha12>.manifest.json` per document: hash, pages, document type, provenance, role (drawing / reference workbook / template), confidentiality notes | no |
| `expected/` | one `<sha12>.expected.json` per PDF (schema `paacc-golden/1`, below) | no |
| `results/` | `golden_run` outputs and `golden_compare` reports | no |

Supply the files from the company's secure storage before running. Never commit them, never paste values into
issues/PRs. The committed `docs/REAL_DRAWING_VALIDATION_REPORT.md` contains only redacted, aggregated findings.

## Run
```bash
cd backend
python -m tools.golden_run --input ../test-data/golden-dataset/drawings --out ../test-data/golden-dataset/results --label current
python -m tools.golden_compare --expected ../test-data/golden-dataset/expected/<sha12>.expected.json \
                               --run ../test-data/golden-dataset/results/<pdf-stem>.current.json \
                               --out ../test-data/golden-dataset/results/<sha12>.compare.json
```
```bash
PAACC_GOLDEN_DIR=../test-data/golden-dataset python -m pytest tests/test_golden_dataset.py   # regression gate; skipped when no data is present
```
`golden_run` uses a throw-away SQLite database and storage directory; it never touches the configured database.

## Expected file (`paacc-golden/1`)
```jsonc
{
  "schema": "paacc-golden/1",
  "document": {"file": "...", "sha256": "...", "pages": 2, "document_type": "...", "is_construction_drawing": false, "verification": "how values were verified"},
  "pages": [{"page_no": 1, "kind": "vector", "drawing_number": null, "title": null, "revision": null, "scale_ratio": null, "units": null}],
  "dimensions": [{"page": 1, "raw": "L=5150mm", "values": ["5150"], "unit": "mm", "kind": "labeled", "status": "verified"},
                 {"page": 1, "raw": "L=6.100mm", "status": "ambiguous", "note": "..."},
                 {"page": 2, "raw": "L=1,89mm", "status": "requires_engineer", "note": "..."}],
  "not_dimensions": [{"page": 2, "raw": "3M", "reason": "brand name"}],
  "materials": [{"page": 1, "raw": "S.509", "category": "traffic_sign"}],
  "boq_rows": [{"page": 1, "group": "1", "description": "...", "unit": "cái", "quantity": "2.00"}],
  "duplicates": [{"page": 1, "description": "...", "quantity": "726.00", "expect": "flag_component_of_parent | no_duplicate_flag | <flag code>"}]
}
```
Rules for expected values:
- Only values verified independently of the pipeline (visual reading of the rendered page, cross-checked with a
  second source where one exists) go into `expected/`.
- `null` means "must NOT be detected" (e.g. no scale on a quotation sheet).
- Anything that cannot be established is `status: "ambiguous"` or `"requires_engineer"`. It is never guessed.

## Classification (`tools/golden_compare.py`)
- **Per expected value:** `CORRECT`, `PARTIALLY_CORRECT`, `INCORRECT` or `MISSING`.
  - Ambiguous or engineer-review expectations are `CORRECT` only when the pipeline flags them instead of silently resolving them.
- **Extracted values that match nothing:** reported as false positives.
- **Percentages:** computed only over verified denominators.
