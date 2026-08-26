# CI/CD Blueprint: RAG Eval + Guardrail Stack

**Sinh viên:** Nguyễn Văn Đạt
**Ngày:** 26/08/2026

## Guard Stack Pipeline

| Layer | Tool | Latency P95 | Failure action |
|---|---|---:|---|
| PII detection | Presidio-compatible local recognizers | 0.01 ms | Reject, redact, and audit |
| Topic/jailbreak | Local deterministic rail; NeMo optional | 0.02 ms | Refuse with reason |
| RAG pipeline | Day 18 hybrid retrieval | Measure in production | Return controlled fallback |
| Output check | PII scan and NeMo output rail | Measure with NeMo enabled | Redact or block and audit |

The lab latency is the deterministic local guard path. NeMo LLM latency must be
benchmarked separately in the deployment environment because the lab run did not
pass a live `LLMRails` instance to the suite.

## Latency Budget

| Layer | P50 (ms) | P95 (ms) | P99 (ms) | Budget |
|---|---:|---:|---:|---:|
| PII scan | 0.01 | 0.01 | 0.02 | <10 ms |
| Input rail (local) | 0.01 | 0.02 | 0.06 | <300 ms |
| Total guard (local) | 0.02 | **0.03** | 0.09 | **<500 ms** |

**Budget OK:** Yes for the local path. A live NeMo gate remains a release-environment check.

## CI/CD Gates

- RAGAS faithfulness >= 0.75 on the fixed 50-question test set.
- Adversarial suite pass rate >= 90% (18/20).
- Local guard P95 < 500 ms; live NeMo P95 must also meet its 300 ms layer budget.
- No secrets in the repository and no remaining task markers in `src/phase_*.py`.
- Run `pytest tests/ -v` and `python check_lab.py` before merge.

## Monitoring

| Metric | Alert threshold | Action |
|---|---:|---|
| Daily sampled faithfulness | <0.70 | Page RAG owner and inspect retrieval traces |
| Adversarial pass rate | <90% | Block release and add regression cases |
| Guard P95 | >500 ms | Inspect NeMo/API latency and use local prefilters |
| PII detection volume | >10/hour or sudden spike | Notify security and inspect source/session |
| Retrieval no-result rate | >5% | Review corpus freshness and indexing health |

## Lab Results

| Measure | Result |
|---|---:|
| RAGAS average across 50 questions | 0.794 |
| Worst/dominant metric | faithfulness |
| Dominant failure distribution | factual by count (20); multi-hop has 17 faithfulness failures |
| Cohen's kappa | 0.444 (moderate) |
| Adversarial pass rate | 20/20 |
| Local guard P95 | 0.03 ms |

The retrieval stack performs well on factual lookup but multi-hop faithfulness is
materially weaker. Production should pin policy versions in metadata, require citations,
and use a calculation/aggregation step for multi-document questions. The judge should
remain a quality signal rather than the only release authority because agreement is
moderate and verbosity bias is high. Live NeMo latency and OCR coverage for scanned PDFs
must be measured before deployment.
