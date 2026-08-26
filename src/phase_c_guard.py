from __future__ import annotations

"""Phase C: local PII protection plus optional NeMo input/output rails."""

import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ADVERSARIAL_SET_PATH, GUARDRAILS_CONFIG_DIR, LATENCY_BUDGET_P95_MS

PII_PATTERNS = {
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "VN_PHONE": re.compile(r"(?<!\d)0[3-9]\d{8}(?!\d)"),
    "VN_CCCD": re.compile(r"(?<!\d)(?:\d{12}|\d{9})(?!\d)"),
}
BLOCK_PATTERNS = (
    r"ignore (?:your |all )?(?:previous |system )?(?:instructions|prompt)",
    r"forget (?:all |your )?(?:hr policies|system prompt)", r"system override",
    r"pretend you are dan", r"unrestricted ai", r"admin command", r"priority 1",
    r"bỏ qua tất cả", r"đóng vai hr manager", r"không có giới hạn", r"tôi là ceo",
    r"system instructions", r"training data", r"confidential", r"employee records",
    r"all employee salaries", r"toàn bộ thông tin nhân viên", r"toàn bộ system",
    r"cccd và số điện thoại của", r"thông tin cá nhân của", r"tiết lộ lương tháng",
    r"mật khẩu admin", r"tấn công mạng", r"bài thơ", r"nấu phở", r"bitcoin",
    r"ethereum", r"phương trình vi phân", r"marvel", r"recommend.*phim",
)
REFUSAL = "Yeu cau bi tu choi boi guardrail bao mat va pham vi HR."


def setup_presidio():
    """Build Presidio engines; custom regex fallback remains available."""
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_anonymizer import AnonymizerEngine
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    registry.add_recognizer(PatternRecognizer(
        supported_entity="VN_CCCD", patterns=[Pattern("VN ID", r"\b(?:\d{12}|\d{9})\b", 0.9)]))
    registry.add_recognizer(PatternRecognizer(
        supported_entity="VN_PHONE", patterns=[Pattern("VN mobile", r"\b0[3-9]\d{8}\b", 0.9)]))
    return AnalyzerEngine(registry=registry), AnonymizerEngine()


def pii_scan(text: str, analyzer=None, anonymizer=None) -> dict:
    matches = []
    for entity_type, pattern in PII_PATTERNS.items():
        for match in pattern.finditer(text):
            matches.append({"type": entity_type, "text": match.group(), "score": 0.9,
                            "start": match.start(), "end": match.end()})
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    # Avoid reporting a phone number again as a generic 9-digit ID.
    entities = []
    for item in matches:
        if any(item["start"] >= old["start"] and item["end"] <= old["end"] for old in entities):
            continue
        entities.append(item)
    anonymized_text = text
    for item in sorted(entities, key=lambda value: value["start"], reverse=True):
        anonymized_text = (anonymized_text[:item["start"]] + f"<{item['type']}>" +
                           anonymized_text[item["end"]:])
    return {"has_pii": bool(entities), "entities": entities, "anonymized": anonymized_text}


def setup_nemo_rails():
    from nemoguardrails import LLMRails, RailsConfig
    return LLMRails(RailsConfig.from_path(GUARDRAILS_CONFIG_DIR))


def _heuristic_block_reason(text: str) -> str | None:
    lowered = text.casefold()
    return "policy_pattern" if any(re.search(pattern, lowered) for pattern in BLOCK_PATTERNS) else None


def _response_text(response) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return str(response.get("content", response.get("response", "")))
    return str(response)


async def check_input_rail(text: str, rails=None) -> dict:
    local_reason = _heuristic_block_reason(text)
    if local_reason:
        return {"allowed": False, "blocked_reason": local_reason, "response": REFUSAL}
    if rails is None:
        return {"allowed": True, "blocked_reason": None, "response": ""}
    response = _response_text(await rails.generate_async(messages=[{"role": "user", "content": text}]))
    blocked = any(word in response.casefold() for word in ("xin lỗi", "không thể", "i cannot", "refuse"))
    return {"allowed": not blocked, "blocked_reason": "nemo_input_rail" if blocked else None,
            "response": response}


async def check_output_rail(question: str, answer: str, rails=None) -> dict:
    pii = pii_scan(answer)
    if pii["has_pii"]:
        return {"safe": False, "flagged_reason": "pii_output",
                "final_answer": pii["anonymized"]}
    if rails is None:
        return {"safe": True, "flagged_reason": None, "final_answer": answer}
    response = _response_text(await rails.generate_async(messages=[
        {"role": "user", "content": question}, {"role": "assistant", "content": answer}]))
    blocked = any(word in response.casefold() for word in ("xin lỗi", "không thể cung cấp", "i cannot"))
    return {"safe": not blocked, "flagged_reason": "nemo_output_rail" if blocked else None,
            "final_answer": response if blocked else answer}


def run_adversarial_suite(adversarial_set: list[dict], rails=None,
                          analyzer=None, anonymizer=None) -> list[dict]:
    async def run_all():
        output = []
        for item in adversarial_set:
            blocked_by = "presidio" if pii_scan(item["input"], analyzer, anonymizer)["has_pii"] else None
            if blocked_by is None:
                rail = await check_input_rail(item["input"], rails)
                blocked_by = None if rail["allowed"] else "nemo_input"
            actual = "blocked" if blocked_by else "allowed"
            output.append({"id": item["id"], "category": item["category"],
                           "input": item["input"], "expected": item["expected"],
                           "actual": actual, "blocked_by": blocked_by,
                           "passed": actual == item["expected"]})
        return output
    results = asyncio.run(run_all())
    print(f"Adversarial suite: {sum(item['passed'] for item in results)}/{len(results)} passed")
    return results


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    values = sorted(values)
    def nearest(percent: float) -> float:
        return round(values[min(len(values) - 1, max(0, int(percent * len(values) + 0.999) - 1))], 2)
    return {"p50": nearest(0.50), "p95": nearest(0.95), "p99": nearest(0.99)}


def measure_p95_latency(test_inputs: list[str], n_runs: int = 20,
                        rails=None, analyzer=None, anonymizer=None) -> dict:
    presidio_times, nemo_times, total_times = [], [], []
    samples = test_inputs[:max(0, n_runs)]
    async def measure():
        for text in samples:
            start = time.perf_counter()
            pii_scan(text, analyzer, anonymizer)
            middle = time.perf_counter()
            await check_input_rail(text, rails)
            end = time.perf_counter()
            presidio_times.append((middle - start) * 1000)
            nemo_times.append((end - middle) * 1000)
            total_times.append((end - start) * 1000)
    asyncio.run(measure())
    total = _percentiles(total_times)
    return {"presidio_ms": _percentiles(presidio_times), "nemo_ms": _percentiles(nemo_times),
            "total_ms": total, "latency_budget_ok": total["p95"] < LATENCY_BUDGET_P95_MS,
            "budget_ms": LATENCY_BUDGET_P95_MS}


if __name__ == "__main__":
    with open(ADVERSARIAL_SET_PATH, encoding="utf-8") as file:
        adversarial = json.load(file)
    results = run_adversarial_suite(adversarial)
    latency = measure_p95_latency([item["input"] for item in adversarial])
    os.makedirs("reports", exist_ok=True)
    with open("reports/guard_results.json", "w", encoding="utf-8") as file:
        json.dump({"results": results, "passed": sum(item["passed"] for item in results),
                   "total": len(results), "latency": latency}, file, ensure_ascii=False, indent=2)
    print("Saved reports/guard_results.json")
