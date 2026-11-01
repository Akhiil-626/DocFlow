# DocFlow Local Model Pipeline Evaluation Report

- **Date**: 2026-11-01 11:08:22 UTC
- **Provider**: `OLLAMA`
- **Models Evaluated**: `llama3.2:3b`, `llama3.1:8b`
- **Hardware Specification**: Intel Core i7-1165G7 @ 2.80GHz, 16GB RAM, Intel Iris Xe Integrated Graphics (No Dedicated GPU)
- **Repetitions per Invoice**: 1

## Model Comparison Matrix

| Metric | **llama3.2:3b (OLLAMA)** | **llama3.1:8b (OLLAMA)** |
| :--- | :---: | :---: |
| **Invoice Accuracy (All Fields Correct)** | 90.0% (18/20) | 100.0% (20/20) |
| **Critical-Fields Accuracy** | 95.0% (19/20) | 100.0% (20/20) |
| **Line Item Description Similarity** | 100.0% | 100.0% |
| **Silent Error Rate (Wrong in Auto-Approved)** | **0.0%** (0/7) | **0.0%** (0/8) |
| **Validation Catch Rate (Caught / Total Wrong)** | 100.0% (2/2) | 100.0% (0/0) |
| **Pipeline Routing (Auto / Review / Fail)** | 35.0% / 65.0% / 0.0% | 40.0% / 60.0% / 0.0% |
| **Latency (Median p50 / p95)** | 19.062s / 31.534s | 37.366s / 58.395s |
| **Avg Tokens / Invoice** | 1160.4 | 1151.0 |
| **Repair Retries Used** | 0 | 0 |
| **Invalid Output Failures** | 0 | 0 |
| **Consistency across Repeats** | 100.0% (20/20) | 100.0% (20/20) |

---

## Field-by-Field Extraction Accuracy

| Field | **llama3.2:3b (OLLAMA)** | **llama3.1:8b (OLLAMA)** |
| :--- | :---: | :---: |
| `vendor_name` | 100.0% | 100.0% |
| `vendor_gstin` | 100.0% | 100.0% |
| `invoice_number` | 100.0% | 100.0% |
| `invoice_date` | 100.0% | 100.0% |
| `currency` | 95.0% | 100.0% |
| `subtotal` | 100.0% | 100.0% |
| `cgst` | 100.0% | 100.0% |
| `sgst` | 100.0% | 100.0% |
| `igst` | 100.0% | 100.0% |
| `total` | 95.0% | 100.0% |
| `line_items` | 100.0% | 100.0% |

---

## Most Common Mistakes per Model

### Model: `llama3.2:3b` (OLLAMA)
- **`currency`**: 1 errors (5.0% of samples)
- **`total`**: 1 errors (5.0% of samples)

### Model: `llama3.1:8b` (OLLAMA)
- No field extraction errors recorded across tested sample invoices.

---

## Per-Invoice Extraction Results

| File Name | Model | Pipeline Status | Validation Issues | Wrong Fields | Flag |
| :--- | :--- | :--- | :--- | :--- | :--- |
| bad_invoice_01.pdf | llama3.2:3b | needs_review | TOTAL_MISMATCH | None | - |
| bad_invoice_02.pdf | llama3.2:3b | needs_review | LINE_ITEM_AMOUNT_MISMATCH | None | - |
| bad_invoice_03.pdf | llama3.2:3b | needs_review | LINE_ITEMS_SUM_MISMATCH | None | - |
| bad_invoice_04.pdf | llama3.2:3b | needs_review | TAX_TYPE_CONFLICT, UNEXPECTED_TAX_RATE | None | - |
| bad_invoice_05.pdf | llama3.2:3b | needs_review | INVALID_GSTIN | None | - |
| bad_invoice_06.pdf | llama3.2:3b | needs_review | FUTURE_INVOICE_DATE | None | - |
| bad_invoice_07.pdf | llama3.2:3b | needs_review | NEGATIVE_AMOUNT, NEGATIVE_AMOUNT, LINE_ITEMS_SUM_MISMATCH | None | - |
| bad_invoice_08.pdf | llama3.2:3b | needs_review | CGST_SGST_MISMATCH, UNEXPECTED_TAX_RATE | None | - |
| bad_invoice_09.pdf | llama3.2:3b | needs_review | OLD_INVOICE_DATE | None | - |
| bad_invoice_10.pdf | llama3.2:3b | needs_review | OLD_INVOICE_DATE, DUPLICATE_SUSPECTED | None | - |
| invoice_01.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_02.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_03.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_04.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_05.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_06.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_07.pdf | llama3.2:3b | needs_review | MISSING_GSTIN | None | - |
| invoice_08.pdf | llama3.2:3b | auto_approved | None | None | - |
| invoice_09.pdf | llama3.2:3b | needs_review | TOTAL_MISMATCH | total | - |
| invoice_10.pdf | llama3.2:3b | needs_review | MISSING_GSTIN | currency | - |
| bad_invoice_01.pdf | llama3.1:8b | needs_review | TOTAL_MISMATCH | None | - |
| bad_invoice_02.pdf | llama3.1:8b | needs_review | LINE_ITEM_AMOUNT_MISMATCH | None | - |
| bad_invoice_03.pdf | llama3.1:8b | needs_review | LINE_ITEMS_SUM_MISMATCH | None | - |
| bad_invoice_04.pdf | llama3.1:8b | needs_review | TAX_TYPE_CONFLICT, UNEXPECTED_TAX_RATE | None | - |
| bad_invoice_05.pdf | llama3.1:8b | needs_review | INVALID_GSTIN | None | - |
| bad_invoice_06.pdf | llama3.1:8b | needs_review | FUTURE_INVOICE_DATE | None | - |
| bad_invoice_07.pdf | llama3.1:8b | needs_review | NEGATIVE_AMOUNT, NEGATIVE_AMOUNT, LINE_ITEMS_SUM_MISMATCH | None | - |
| bad_invoice_08.pdf | llama3.1:8b | needs_review | CGST_SGST_MISMATCH, UNEXPECTED_TAX_RATE | None | - |
| bad_invoice_09.pdf | llama3.1:8b | needs_review | OLD_INVOICE_DATE | None | - |
| bad_invoice_10.pdf | llama3.1:8b | needs_review | OLD_INVOICE_DATE, DUPLICATE_SUSPECTED | None | - |
| invoice_01.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_02.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_03.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_04.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_05.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_06.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_07.pdf | llama3.1:8b | needs_review | MISSING_GSTIN | None | - |
| invoice_08.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_09.pdf | llama3.1:8b | auto_approved | None | None | - |
| invoice_10.pdf | llama3.1:8b | needs_review | MISSING_GSTIN | None | - |
