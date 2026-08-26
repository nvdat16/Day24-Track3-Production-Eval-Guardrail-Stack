# Failure Cluster Analysis - Phase A

**Sinh vien:** Nguyễn Văn Đạt
**Ngay:** 2026-08-26

## Aggregate Scores

| Metric | factual | multi_hop | adversarial |
|---|---:|---:|---:|
| faithfulness | 0.846 | 0.462 | 0.900 |
| answer_relevancy | 0.757 | 0.751 | 0.704 |
| context_precision | 0.983 | 0.933 | 1.000 |
| context_recall | 0.825 | 0.792 | 0.650 |
| **avg_score** | **0.853** | **0.735** | **0.813** |

## Bottom 10

| Rank | ID | Distribution | avg_score | worst metric |
|---:|---:|---|---:|---|
| 1 | 6 | factual | 0.2083 | faithfulness |
| 2 | 33 | multi_hop | 0.3333 | faithfulness |
| 3 | 21 | multi_hop | 0.3750 | faithfulness |
| 4 | 50 | adversarial | 0.4167 | faithfulness |
| 5 | 9 | factual | 0.5000 | faithfulness |
| 6 | 24 | multi_hop | 0.6125 | faithfulness |
| 7 | 31 | multi_hop | 0.6217 | faithfulness |
| 8 | 48 | adversarial | 0.6667 | answer_relevancy |
| 9 | 30 | multi_hop | 0.6786 | faithfulness |
| 10 | 5 | factual | 0.6799 | context_recall |

## Failure Matrix

| worst metric | factual | multi_hop | adversarial | total |
|---|---:|---:|---:|---:|
| faithfulness | 5 | 17 | 1 | 23 |
| answer_relevancy | 11 | 0 | 1 | 12 |
| context_precision | 0 | 1 | 0 | 1 |
| context_recall | 4 | 2 | 8 | 14 |

## Analysis and Fixes

The dominant metric is faithfulness (23 cases). Factual is the dominant distribution by
raw failure count because each distribution assigns one worst metric per question and
factual has 20 questions, tied with multi-hop. The actionable concentration is more
specific: 17/20 multi-hop questions have faithfulness as their worst metric. These
questions require cross-document arithmetic or policy combination, where retrieval alone
does not guarantee a supported conclusion.

Use policy-version metadata filters, preserve source/version fields during enrichment,
require sentence-level citations, and add a deterministic calculator for monetary and
leave-day arithmetic. Improve adversarial recall with query expansion and explicit
retrieval of both current and superseded policy versions. Context precision is already
strong, so increasing top-k indiscriminately would likely add noise.

Adversarial average (0.813) is below factual (0.853), as expected, but above multi-hop
(0.735). Two adversarial questions enter the bottom 10: personal VPN use (faithfulness)
and probationary PVI coverage (answer relevancy). This points to policy contradiction and
negation handling rather than broad retrieval noise.
