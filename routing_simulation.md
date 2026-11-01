| Policy | Invoice Accuracy | Critical-Fields Accuracy | Silent Error Rate | Auto-Approved % | Escalation % | Median Latency (s) | p95 Latency (s) | Total Compute (s) | Useful Escalations | Wasted Escalations |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| P1: Small model only | 90.0% | 95.0% | 0.0% | 35.0% | 0.0% | 19.062s | 31.534s | 425.39s | 0 | 0 |
| P2: Large model only | 100.0% | 100.0% | 0.0% | 40.0% | 0.0% | 37.366s | 58.395s | 850.81s | 0 | 0 |
| P3: Escalate on ANY error | 95.0% | 100.0% | 0.0% | 40.0% | 40.0% | 25.648s | 71.356s | 778.02s | 1 | 7 |
| P4: Escalate on ESCALATE_CODES | 95.0% | 100.0% | 0.0% | 40.0% | 25.0% | 21.192s | 71.356s | 668.84s | 1 | 4 |
| P5: P4 + skip document issues | 95.0% | 100.0% | 0.0% | 40.0% | 25.0% | 21.192s | 71.356s | 668.84s | 1 | 4 |
