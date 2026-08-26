from __future__ import annotations

"""Phase B: pairwise LLM judging, consistency, agreement, and bias."""

import json
import os
import sys
from dataclasses import asdict, dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HUMAN_LABELS_PATH, JUDGE_MODEL, OPENAI_API_KEY, TEST_SET_PATH


@dataclass
class JudgeResult:
    question: str
    answer_a: str
    answer_b: str
    winner_pass1: str
    winner_pass2: str
    final_winner: str
    reasoning_pass1: str
    reasoning_pass2: str
    position_consistent: bool
    scores_pass1: dict = field(default_factory=dict)
    scores_pass2: dict = field(default_factory=dict)


def _normalise_judgement(value: dict) -> dict:
    winner = str(value.get("winner", "tie"))
    if winner not in {"A", "B", "tie"}:
        winner = "tie"
    scores = value.get("scores") if isinstance(value.get("scores"), dict) else {}
    return {"winner": winner,
            "reasoning": str(value.get("reasoning") or "No decisive quality difference."),
            "scores": {key: max(0.0, min(1.0, float(scores.get(key, 0.5))))
                       for key in ("A", "B")}}


def pairwise_judge(question: str, answer_a: str, answer_b: str) -> dict:
    if not OPENAI_API_KEY:
        return {"winner": "tie", "reasoning": "OPENAI_API_KEY is not configured.",
                "scores": {"A": 0.5, "B": 0.5}}
    from openai import OpenAI
    prompt = f"""Evaluate two RAG answers for accuracy, completeness, and conciseness.
Question: {question}
Answer A: {answer_a}
Answer B: {answer_b}
Return JSON only: {{"winner":"A|B|tie","reasoning":"...","scores":{{"A":0.0,"B":0.0}}}}"""
    response = OpenAI(api_key=OPENAI_API_KEY).chat.completions.create(
        model=JUDGE_MODEL, temperature=0,
        messages=[{"role": "system", "content": "You are an impartial RAG evaluator."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return _normalise_judgement(json.loads(response.choices[0].message.content))


def swap_and_average(question: str, answer_a: str, answer_b: str) -> JudgeResult:
    first = pairwise_judge(question, answer_a, answer_b)
    second_raw = pairwise_judge(question, answer_b, answer_a)
    swapped = {"A": "B", "B": "A", "tie": "tie"}
    second_winner = swapped[second_raw["winner"]]
    consistent = first["winner"] == second_winner
    return JudgeResult(
        question=question, answer_a=answer_a, answer_b=answer_b,
        winner_pass1=first["winner"], winner_pass2=second_winner,
        final_winner=first["winner"] if consistent else "tie",
        reasoning_pass1=first["reasoning"], reasoning_pass2=second_raw["reasoning"],
        position_consistent=consistent, scores_pass1=first["scores"],
        scores_pass2={"A": second_raw["scores"]["B"], "B": second_raw["scores"]["A"]},
    )


def cohen_kappa(judge_labels: list[int], human_labels: list[int]) -> float:
    if len(judge_labels) != len(human_labels):
        raise ValueError("Judge and human label lists must have equal length")
    if not judge_labels:
        return 0.0
    if any(label not in (0, 1) for label in judge_labels + human_labels):
        raise ValueError("Cohen kappa labels must be binary (0 or 1)")
    n = len(judge_labels)
    observed = sum(a == b for a, b in zip(judge_labels, human_labels)) / n
    expected = ((judge_labels.count(1) * human_labels.count(1)) +
                (judge_labels.count(0) * human_labels.count(0))) / (n * n)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return max(-1.0, min(1.0, (observed - expected) / (1.0 - expected)))


def bias_report(judge_results: list[JudgeResult]) -> dict:
    total = len(judge_results)
    inconsistent = sum(not result.position_consistent for result in judge_results)
    decisive = [result for result in judge_results if result.final_winner != "tie"]
    a_longer = sum(result.final_winner == "A" and len(result.answer_a) > len(result.answer_b)
                   for result in decisive)
    b_longer = sum(result.final_winner == "B" and len(result.answer_b) > len(result.answer_a)
                   for result in decisive)
    position_rate = inconsistent / total if total else 0.0
    verbosity_rate = (a_longer + b_longer) / len(decisive) if decisive else 0.0
    return {"total_judged": total, "position_bias_rate": round(position_rate, 3),
            "position_bias_count": inconsistent, "verbosity_bias": round(verbosity_rate, 3),
            "verbosity_details": {"a_wins_a_longer": a_longer,
                                  "b_wins_b_longer": b_longer,
                                  "total_decisive": len(decisive)},
            "interpretation": ("Position bias is high; retain swap-and-average."
                               if position_rate > 0.3 else "Position bias is within the target range.")}


if __name__ == "__main__":
    with open(HUMAN_LABELS_PATH, encoding="utf-8") as file:
        labelled = json.load(file)
    with open(TEST_SET_PATH, encoding="utf-8") as file:
        ground_truths = {item["id"]: item["ground_truth"] for item in json.load(file)}
    comparisons = [swap_and_average(item["question"], item["model_answer"],
                                    ground_truths[item["question_id"]]) for item in labelled]
    # A tie means the model answer is equivalent to the reference and is therefore acceptable.
    judge_labels = [0 if result.final_winner == "B" else 1 for result in comparisons]
    human_labels = [item["human_label"] for item in labelled]
    report = {"results": [asdict(result) for result in comparisons],
              "cohen_kappa": cohen_kappa(judge_labels, human_labels),
              "judge_labels": judge_labels, "human_labels": human_labels,
              "bias": bias_report(comparisons)}
    os.makedirs("reports", exist_ok=True)
    with open("reports/judge_results.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    print("Saved reports/judge_results.json")
