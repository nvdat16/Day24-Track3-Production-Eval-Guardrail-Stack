from __future__ import annotations

"""Phase A: RAGAS evaluation across the three test distributions."""

import json
import os
import sys
from dataclasses import asdict, dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ANSWERS_PATH, TEST_SET_PATH

Distribution = str
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
DIAGNOSTIC_TREE = {
    "faithfulness": ("LLM hallucinating", "Tighten system prompt and lower temperature"),
    "context_recall": ("Missing relevant chunks", "Improve chunking or add BM25"),
    "context_precision": ("Too many irrelevant chunks", "Add reranking or metadata filters"),
    "answer_relevancy": ("Answer does not match the question", "Improve the prompt template"),
}


@dataclass
class RagasResult:
    question_id: int
    distribution: Distribution
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float

    @property
    def avg_score(self) -> float:
        return sum(getattr(self, metric) for metric in METRICS) / len(METRICS)

    @property
    def worst_metric(self) -> str:
        return min(METRICS, key=lambda metric: getattr(self, metric))


def load_test_set_50q(path: str = TEST_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def load_answers(path: str = ANSWERS_PATH) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing {path}. Run: python setup_answers.py")
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def group_by_distribution(test_set: list[dict]) -> dict[str, list[dict]]:
    groups = {"factual": [], "multi_hop": [], "adversarial": []}
    for item in test_set:
        distribution = item.get("distribution")
        if distribution not in groups:
            raise ValueError(f"Unknown distribution: {distribution!r}")
        groups[distribution].append(item)
    return groups


def run_ragas_50q(answers: list[dict]) -> list[RagasResult]:
    from src.m4_eval import evaluate_ragas

    required = {"id", "distribution", "question", "answer", "contexts", "ground_truth"}
    for index, item in enumerate(answers):
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Answer {index} is missing fields: {sorted(missing)}")
    raw = evaluate_ragas(
        [item["question"] for item in answers], [item["answer"] for item in answers],
        [item["contexts"] for item in answers], [item["ground_truth"] for item in answers],
    )
    rows = raw.get("per_question", [])
    if len(rows) != len(answers):
        raise RuntimeError(f"RAGAS returned {len(rows)} rows for {len(answers)} answers")

    def score(row, metric: str) -> float:
        value = row.get(metric, 0.0) if isinstance(row, dict) else getattr(row, metric, 0.0)
        value = float(value)
        return 0.0 if value != value else max(0.0, min(1.0, value))

    return [RagasResult(
        question_id=item["id"], distribution=item["distribution"], question=item["question"],
        answer=item["answer"], contexts=item["contexts"], ground_truth=item["ground_truth"],
        **{metric: score(row, metric) for metric in METRICS},
    ) for item, row in zip(answers, rows)]


def bottom_10(results: list[RagasResult]) -> list[dict]:
    output = []
    for rank, result in enumerate(sorted(results, key=lambda row: row.avg_score)[:10], 1):
        diagnosis, suggested_fix = DIAGNOSTIC_TREE[result.worst_metric]
        output.append({"rank": rank, "question_id": result.question_id,
                       "distribution": result.distribution, "question": result.question,
                       "avg_score": round(result.avg_score, 4),
                       "worst_metric": result.worst_metric, "diagnosis": diagnosis,
                       "suggested_fix": suggested_fix})
    return output


def cluster_analysis(results: list[RagasResult]) -> dict:
    distributions = ("factual", "multi_hop", "adversarial")
    matrix = {metric: {dist: 0 for dist in distributions} for metric in METRICS}
    for result in results:
        if result.distribution not in distributions:
            raise ValueError(f"Unknown distribution: {result.distribution!r}")
        matrix[result.worst_metric][result.distribution] += 1
    dominant_dist = max(distributions, key=lambda dist: sum(row[dist] for row in matrix.values()))
    dominant_metric = max(METRICS, key=lambda metric: sum(matrix[metric].values()))
    return {"matrix": matrix, "dominant_failure_distribution": dominant_dist,
            "dominant_failure_metric": dominant_metric,
            "insight": (f"{dominant_dist} has the most failures and {dominant_metric} is the "
                        f"dominant weak metric. {DIAGNOSTIC_TREE[dominant_metric][1]}.")}


def save_phase_a_report(results: list[RagasResult], clusters: dict,
                        path: str = "reports/ragas_50q.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    per_distribution = {}
    for dist, subset in group_by_distribution([asdict(row) for row in results]).items():
        if subset:
            per_distribution[dist] = {"count": len(subset), **{
                metric: sum(row[metric] for row in subset) / len(subset) for metric in METRICS
            }, "avg_score": sum(sum(row[m] for m in METRICS) / 4 for row in subset) / len(subset)}
    report = {"total_questions": len(results), "per_distribution": per_distribution,
              "failure_clusters": clusters, "bottom_10": bottom_10(results)}
    with open(path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    evaluated = run_ragas_50q(load_answers())
    save_phase_a_report(evaluated, cluster_analysis(evaluated))
    print(f"Evaluated {len(evaluated)} questions -> reports/ragas_50q.json")
