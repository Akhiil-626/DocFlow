# DocFlow Extraction & Validation Evaluation Report

Generated: 2026-10-18 13:35:12 UTC

Provider: `MockLLMClient` (`gemini-2.5-flash`)

## Executive Summary

| Metric | Result |
| :--- | :--- |
| **Total Invoices Evaluated** | 20 |
| **Auto-Approved** | 8 (40.0%) |
| **Needs Review** | 12 (60.0%) |
| **Failed** | 0 |
| **Expected Issue Detection Rate** | 11/11 (100.0%) |
| **Average Latency** | 5.0 ms |
| **Average Tokens / Invoice** | 242.0 |

---

## Field-by-Field Extraction Accuracy

| Field | Matches | Accuracy Rate |
| :--- | :--- | :--- |
| `vendor_name` | 20/20 | 100.0% |
| `vendor_gstin` | 20/20 | 100.0% |
| `invoice_number` | 20/20 | 100.0% |
| `invoice_date` | 20/20 | 100.0% |
| `currency` | 20/20 | 100.0% |
| `subtotal` | 20/20 | 100.0% |
| `cgst` | 20/20 | 100.0% |
| `sgst` | 20/20 | 100.0% |
| `igst` | 20/20 | 100.0% |
| `total` | 20/20 | 100.0% |
| `line_items_count` | 20/20 | 100.0% |

---

## Invoice-Level Pipeline Routing & Issue Audit

| Invoice File | Pipeline Status | Issue Count | Detected Issue Codes |
| :--- | :--- | :--- | :--- |
| `bad_invoice_01.pdf` | **needs_review** | 1 | `TOTAL_MISMATCH` |
| `bad_invoice_02.pdf` | **needs_review** | 1 | `LINE_ITEM_AMOUNT_MISMATCH` |
| `bad_invoice_03.pdf` | **needs_review** | 1 | `LINE_ITEMS_SUM_MISMATCH` |
| `bad_invoice_04.pdf` | **needs_review** | 2 | `TAX_TYPE_CONFLICT`, `UNEXPECTED_TAX_RATE` |
| `bad_invoice_05.pdf` | **needs_review** | 1 | `INVALID_GSTIN` |
| `bad_invoice_06.pdf` | **needs_review** | 1 | `FUTURE_INVOICE_DATE` |
| `bad_invoice_07.pdf` | **needs_review** | 3 | `NEGATIVE_AMOUNT`, `NEGATIVE_AMOUNT`, `LINE_ITEMS_SUM_MISMATCH` |
| `bad_invoice_08.pdf` | **needs_review** | 2 | `CGST_SGST_MISMATCH`, `UNEXPECTED_TAX_RATE` |
| `bad_invoice_09.pdf` | **needs_review** | 1 | `OLD_INVOICE_DATE` |
| `bad_invoice_10.pdf` | **needs_review** | 2 | `OLD_INVOICE_DATE`, `DUPLICATE_SUSPECTED` |
| `invoice_01.pdf` | **auto_approved** | 0 | — |
| `invoice_02.pdf` | **auto_approved** | 0 | — |
| `invoice_03.pdf` | **auto_approved** | 0 | — |
| `invoice_04.pdf` | **auto_approved** | 0 | — |
| `invoice_05.pdf` | **auto_approved** | 0 | — |
| `invoice_06.pdf` | **auto_approved** | 0 | — |
| `invoice_07.pdf` | **needs_review** | 1 | `MISSING_GSTIN` |
| `invoice_08.pdf` | **auto_approved** | 0 | — |
| `invoice_09.pdf` | **auto_approved** | 0 | — |
| `invoice_10.pdf` | **needs_review** | 1 | `MISSING_GSTIN` |
