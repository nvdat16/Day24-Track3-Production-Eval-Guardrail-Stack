# LLM Judge Bias Report - Phase B

**Sinh vien:** Nguyễn Văn Đạt
**Ngay:** 2026-08-26
**Judge model:** gpt-4o-mini

## Method

Ten labelled model answers were compared pairwise against the matching ground truth.
Every pair was judged twice with answer order swapped. A model answer received label 1
when it won or tied the reference, and label 0 when the reference won.

## Results

| Measure | Result |
|---|---:|
| Total judged | 10 |
| Position inconsistencies | 2 |
| Position bias rate | 20.0% |
| Decisive comparisons | 8 |
| Longer winner among decisive cases | 7 |
| Verbosity bias rate | 87.5% |
| Cohen's kappa | 0.444 |

Judge labels were `[1,0,0,1,0,0,0,0,1,0]`; human labels were
`[1,0,1,1,1,0,1,0,1,0]`. The agreement is **moderate**, below the 0.6 substantial
threshold. Swap-and-average caught two order-sensitive cases, so retaining it is useful.

The 87.5% verbosity association is high, although this small sample does not prove
causation: the reference answers also tend to be more complete and therefore longer.
Production evaluation should blind answer identity, keep swap-and-average, calibrate on a
larger balanced human-labelled set, and route disagreements or low-margin scores to human
review. The judge should not be the sole CI gate until kappa improves.
