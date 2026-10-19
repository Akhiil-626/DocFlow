import json
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.llm import get_llm_client
from app.models import Document, Extraction, Organization, User, ValidationIssue
from app.security import hash_password
from app.storage import LocalStorage
from app.worker.tasks import process_document

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
RESULTS_FILE = Path(__file__).resolve().parent.parent / "evaluation_results.md"


def run_evaluation():
    db: Session = SessionLocal()
    storage = LocalStorage(settings.UPLOAD_DIR)
    llm_client = get_llm_client()

    print(f"=== DocFlow Week 3 Pipeline Evaluation (Provider: {type(llm_client).__name__}) ===")

    # 1. Create isolated test organization and user
    eval_org_id = uuid.uuid4()
    test_org = Organization(id=eval_org_id, name=f"Eval-Org-{int(time.time())}")
    db.add(test_org)

    test_user = User(
        id=uuid.uuid4(),
        org_id=eval_org_id,
        email=f"eval_{int(time.time())}@evaltest.com",
        password_hash=hash_password("eval_pass_123"),
        role="admin",
        is_active=True,
    )
    db.add(test_user)
    db.commit()

    created_doc_ids: list[uuid.UUID] = []
    created_storage_keys: list[str] = []

    try:
        sample_files = sorted(SAMPLES_DIR.glob("*.pdf"))
        if not sample_files:
            print("No samples found in samples/ directory!")
            return

        fields_to_check = [
            "vendor_name",
            "vendor_gstin",
            "invoice_number",
            "invoice_date",
            "currency",
            "subtotal",
            "cgst",
            "sgst",
            "igst",
            "total",
            "line_items_count",
        ]
        field_matches = {f: 0 for f in fields_to_check}
        total_eval_samples = len(sample_files)

        status_counts = {"auto_approved": 0, "needs_review": 0, "failed": 0, "uploaded": 0}
        bad_set_expected_issues_count = 0
        bad_set_detected_issues_count = 0

        latencies: list[int] = []
        tokens_list: list[int] = []

        per_invoice_results = []

        for pdf_path in sample_files:
            json_path = pdf_path.with_suffix(".json")
            if not json_path.exists():
                continue

            with open(json_path, encoding="utf-8") as f:
                ground_truth = json.load(f)

            is_bad_set = "bad_invoice" in pdf_path.name
            expected_issues = ground_truth.get("expected_issues", [])

            # Read PDF and save to storage
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            doc_id = uuid.uuid4()
            created_doc_ids.append(doc_id)
            storage_key = f"{eval_org_id}/{doc_id}.pdf"
            created_storage_keys.append(storage_key)
            storage.save(storage_key, pdf_bytes)

            import hashlib
            sha256 = hashlib.sha256(pdf_bytes).hexdigest()

            doc = Document(
                id=doc_id,
                org_id=eval_org_id,
                uploaded_by=test_user.id,
                original_filename=pdf_path.name,
                content_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256=sha256,
                storage_key=storage_key,
                status="uploaded",
            )
            db.add(doc)
            db.commit()

            # Execute real pipeline task
            start_t = time.time()
            process_document(
                str(doc_id),
                override_llm_client=llm_client,
                override_storage=storage,
                override_db=db,
            )
            elapsed_ms = int((time.time() - start_t) * 1000)

            # Query results
            db.refresh(doc)
            status_counts[doc.status] = status_counts.get(doc.status, 0) + 1

            extraction = db.query(Extraction).filter(Extraction.document_id == doc_id).first()
            extracted_data = extraction.data if extraction else {}
            latency = extraction.latency_ms if extraction else elapsed_ms
            latencies.append(latency)

            in_tok = (extraction.input_tokens or 0) if extraction else 0
            out_tok = (extraction.output_tokens or 0) if extraction else 0
            tokens_list.append(in_tok + out_tok)

            # Check field match vs ground truth
            sample_field_matches = {}
            for field in fields_to_check:
                if field == "line_items_count":
                    gt_val = len(ground_truth.get("line_items", []))
                    ex_val = len(extracted_data.get("line_items", []))
                    matched = (gt_val == ex_val)
                elif field in ["subtotal", "cgst", "sgst", "igst", "total"]:
                    gt_val = Decimal(str(ground_truth.get(field, 0) or 0))
                    ex_val = Decimal(str(extracted_data.get(field, 0) or 0))
                    matched = (gt_val == ex_val)
                else:
                    gt_val = str(ground_truth.get(field) or "").strip().lower()
                    ex_val = str(extracted_data.get(field) or "").strip().lower()
                    matched = (gt_val == ex_val)

                if matched:
                    field_matches[field] += 1
                sample_field_matches[field] = matched

            # Check detected issues
            db_issues = (
                db.query(ValidationIssue)
                .filter(ValidationIssue.document_id == doc_id)
                .all()
            )
            detected_codes = [i.code for i in db_issues]

            if is_bad_set and expected_issues:
                for exp_code in expected_issues:
                    bad_set_expected_issues_count += 1
                    if exp_code in detected_codes:
                        bad_set_detected_issues_count += 1

            per_invoice_results.append({
                "filename": pdf_path.name,
                "status": doc.status,
                "review_reason": doc.review_reason,
                "issue_count": len(db_issues),
                "detected_codes": detected_codes,
                "expected_issues": expected_issues,
                "latency_ms": latency,
                "tokens": in_tok + out_tok,
            })

        # Summary calculations
        auto_app_pct = (status_counts["auto_approved"] / total_eval_samples) * 100
        needs_rev_pct = (status_counts["needs_review"] / total_eval_samples) * 100
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        avg_tokens = sum(tokens_list) / len(tokens_list) if tokens_list else 0

        bad_detection_rate = (
            (bad_set_detected_issues_count / bad_set_expected_issues_count * 100)
            if bad_set_expected_issues_count > 0
            else 100.0
        )

        # Print console table
        print("\n" + "=" * 65)
        print(f"{'EVALUATION RESULTS SUMMARY':^65}")
        print("=" * 65)
        print(f"Total Sample Invoices Processed: {total_eval_samples}")
        print(f"Status Breakdown               : Auto-Approved: {status_counts['auto_approved']} ({auto_app_pct:.1f}%), Needs Review: {status_counts['needs_review']} ({needs_rev_pct:.1f}%), Failed: {status_counts['failed']}")
        print(f"Expected Issue Detection Rate  : {bad_set_detected_issues_count}/{bad_set_expected_issues_count} ({bad_detection_rate:.1f}%) on Bad Set")
        print(f"Average Latency                : {avg_latency:.1f} ms")
        print(f"Average Tokens per Invoice     : {avg_tokens:.1f}")
        print("-" * 65)
        print(f"{'Field':<22} | {'Matches':<12} | {'Accuracy Rate':<15}")
        print("-" * 65)
        for field in fields_to_check:
            m = field_matches[field]
            rate = (m / total_eval_samples) * 100
            print(f"{field:<22} | {m:>2}/{total_eval_samples:<8} | {rate:>6.1f}%")
        print("=" * 65)

        # Write markdown report
        md_content = f"""# DocFlow Extraction & Validation Evaluation Report

Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}\n
Provider: `{type(llm_client).__name__}` (`{settings.LLM_MODEL}`)

## Executive Summary

| Metric | Result |
| :--- | :--- |
| **Total Invoices Evaluated** | {total_eval_samples} |
| **Auto-Approved** | {status_counts['auto_approved']} ({auto_app_pct:.1f}%) |
| **Needs Review** | {status_counts['needs_review']} ({needs_rev_pct:.1f}%) |
| **Failed** | {status_counts['failed']} |
| **Expected Issue Detection Rate** | {bad_set_detected_issues_count}/{bad_set_expected_issues_count} ({bad_detection_rate:.1f}%) |
| **Average Latency** | {avg_latency:.1f} ms |
| **Average Tokens / Invoice** | {avg_tokens:.1f} |

---

## Field-by-Field Extraction Accuracy

| Field | Matches | Accuracy Rate |
| :--- | :--- | :--- |
"""
        for field in fields_to_check:
            m = field_matches[field]
            rate = (m / total_eval_samples) * 100
            md_content += f"| `{field}` | {m}/{total_eval_samples} | {rate:.1f}% |\n"

        md_content += """
---

## Invoice-Level Pipeline Routing & Issue Audit

| Invoice File | Pipeline Status | Issue Count | Detected Issue Codes |
| :--- | :--- | :--- | :--- |
"""
        for res in per_invoice_results:
            codes_str = ", ".join(f"`{c}`" for c in res["detected_codes"]) or "—"
            md_content += f"| `{res['filename']}` | **{res['status']}** | {res['issue_count']} | {codes_str} |\n"

        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nWritten detailed evaluation report to: {RESULTS_FILE}")

    finally:
        # Clean up all created test documents and test organization
        print("\nCleaning up evaluation test data...")
        for skey in created_storage_keys:
            try:
                storage.delete(skey)
            except Exception:
                pass

        db.delete(test_org)
        db.commit()
        db.close()
        print("Cleanup completed safely. Real user data untouched.")


if __name__ == "__main__":
    run_evaluation()
