import json
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000"
SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "invoice_01.pdf"


def run_live_demo():
    print("=== LIVE DEMO: DocFlow Week 2 Invoice Processing Pipeline ===")
    client = httpx.Client(base_url=API_BASE, timeout=30.0)

    # 1. Health check
    health_resp = client.get("/health")
    print(f"Health Check: {health_resp.status_code} {health_resp.json()}")

    # 2. Register
    reg_payload = {
        "org_name": "Apex Global Logistics",
        "email": f"admin_{int(time.time())}@apexlogistics.com",
        "password": "SecurePassword123!",
    }
    print(f"\n1. Registering Organization & Admin: {reg_payload['email']} ...")
    reg_resp = client.post("/auth/register", json=reg_payload)
    print(f"Registration status: {reg_resp.status_code}")

    # 3. Login
    login_resp = client.post("/auth/login", json={"email": reg_payload["email"], "password": reg_payload["password"]})
    print(f"Login status: {login_resp.status_code}")
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 4. Upload sample invoice
    print(f"\n2. Uploading sample invoice ({SAMPLE_PDF.name}) ...")
    with open(SAMPLE_PDF, "rb") as f:
        upload_resp = client.post(
            "/documents",
            headers=headers,
            files={"file": (SAMPLE_PDF.name, f, "application/pdf")},
        )
    print(f"Upload response: {upload_resp.status_code}")
    doc_info = upload_resp.json()
    doc_id = doc_info["id"]
    print(f"Uploaded Document ID: {doc_id} | Initial Status: {doc_info['status']}")

    # 5. Wait / Poll for Celery background worker extraction
    print("\n3. Waiting for background Celery worker processing...")
    max_wait = 15
    start = time.time()
    final_status = doc_info["status"]
    while time.time() - start < max_wait:
        poll_resp = client.get(f"/documents/{doc_id}", headers=headers)
        doc_data = poll_resp.json()
        final_status = doc_data["status"]
        print(f"   [+{int(time.time() - start)}s] Document status: {final_status} (attempts: {doc_data['attempts']})")
        if final_status in ["extracted", "failed"]:
            break
        time.sleep(1)

    # 6. Fetch extraction result
    print(f"\n4. Fetching extraction from /documents/{doc_id}/extraction ...")
    ext_resp = client.get(f"/documents/{doc_id}/extraction", headers=headers)
    print(f"Extraction response status: {ext_resp.status_code}")
    if ext_resp.status_code == 200:
        print("\nExtracted Data:")
        print(json.dumps(ext_resp.json(), indent=2))
    else:
        print(f"Extraction error: {ext_resp.text}")


if __name__ == "__main__":
    run_live_demo()
