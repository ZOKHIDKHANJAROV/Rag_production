import argparse
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx


NEGATIVE_ANSWER_MARKERS = (
    "no information",
    "not found",
    "nothing found",
    "not enough information",
    "llm service is unavailable",
    "\u043d\u0435\u0442 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438",
    "\u043d\u0435\u0442 \u0442\u0430\u043a\u043e\u0439 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438",
    "\u043d\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d",
    "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442",
)


def normalize(value):
    return " ".join(str(value or "").lower().split())


def percentile(values, percentile_value):
    if not values:
        return None

    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * percentile_value
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)

    if lower == upper:
        return round(sorted_values[lower], 2)

    fraction = position - lower
    return round(
        sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction,
        2,
    )


def expected_sources(case):
    values = case.get("expected_sources", case.get("expected_source", []))
    if isinstance(values, str):
        return [values]
    return values


def source_matches(source, expected):
    expected_value = normalize(expected)
    fields = (source.get("document_id"), source.get("filename"))
    return bool(expected_value) and any(
        expected_value in normalize(field) for field in fields
    )


def is_negative_answer(answer):
    normalized_answer = normalize(answer)
    return any(marker in normalized_answer for marker in NEGATIVE_ANSWER_MARKERS)


def evaluate_response(case, payload, latency_ms, source_limit):
    answer = payload.get("answer", "")
    sources = payload.get("sources", [])[:source_limit]
    expected_source_values = expected_sources(case)
    expected_terms = case.get("expected_answer_contains", [])
    answerable = case.get("expect_answerable", True)

    source_hit = None
    if expected_source_values:
        source_hit = any(
            source_matches(source, expected)
            for source in sources
            for expected in expected_source_values
        )

    answer_match = None
    if expected_terms:
        normalized_answer = normalize(answer)
        answer_match = all(normalize(term) in normalized_answer for term in expected_terms)

    refusal_correct = None
    if not answerable:
        refusal_correct = is_negative_answer(answer)

    return {
        "id": case["id"],
        "latency_ms": round(latency_ms, 2),
        "source_hit": source_hit,
        "answer_match": answer_match,
        "refusal_correct": refusal_correct,
        "source_backed": bool(sources) and not is_negative_answer(answer),
        "source_count": len(sources),
    }


def rate(results, field):
    values = [result[field] for result in results if result[field] is not None]
    return round(sum(values) / len(values), 4) if values else None


def build_report(results, request_errors):
    latencies = [result["latency_ms"] for result in results]
    source_backed = [result["source_backed"] for result in results]

    return {
        "cases": len(results),
        "request_errors": request_errors,
        "source_hit_at_k": rate(results, "source_hit"),
        "answer_keyword_match_rate": rate(results, "answer_match"),
        "refusal_accuracy": rate(results, "refusal_correct"),
        "source_backed_answer_rate": round(sum(source_backed) / len(source_backed), 4)
        if source_backed
        else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
        },
        "results": results,
    }


def load_cases(path):
    with path.open(encoding="utf-8") as handle:
        cases = json.load(handle)

    if not isinstance(cases, list) or not cases:
        raise ValueError("The evaluation dataset must be a non-empty JSON array")

    for case in cases:
        if not case.get("id") or not case.get("question"):
            raise ValueError("Every evaluation case needs id and question")

    return cases


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate RAG answers against a curated dataset")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--url", default="http://localhost:8003/ask")
    parser.add_argument("--source-limit", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-source-hit", type=float, default=0.0)
    return parser.parse_args()


def main():
    args = parse_args()
    cases = load_cases(args.dataset)
    token = os.getenv("INTERNAL_SERVICE_TOKEN", "")
    headers = {"X-Service-Token": token} if token else {}
    results = []
    request_errors = 0

    with httpx.Client(timeout=args.timeout) as client:
        for case in cases:
            started_at = time.perf_counter()
            try:
                response = client.post(
                    args.url,
                    json={
                        "question": case["question"],
                        "session_id": f"eval-{uuid.uuid4()}",
                        "scope_keys": case.get("scope_keys", ["global"]),
                    },
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                request_errors += 1
                results.append({
                    "id": case["id"],
                    "error": str(error),
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                })
                continue

            results.append(
                evaluate_response(
                    case,
                    payload,
                    (time.perf_counter() - started_at) * 1000,
                    args.source_limit,
                )
            )

    successful_results = [result for result in results if "error" not in result]
    report = build_report(successful_results, request_errors)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    source_hit = report["source_hit_at_k"]
    if request_errors or (source_hit is not None and source_hit < args.min_source_hit):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
