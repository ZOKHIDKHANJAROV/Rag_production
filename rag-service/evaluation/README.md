# RAG evaluation

This tool measures retrieval quality and answer quality against a curated set of real questions. The dataset is intentionally local: it may contain private document names and facts.

1. Copy `questions.example.json` to `questions.local.json`.
2. Replace the placeholder with real cases. Every case requires `id` and `question`.
3. Add `expected_sources` with exact filename fragments or document IDs. Optional `expected_answer_contains` values are checked against the final answer.
4. Run the evaluation inside the RAG container after the stack is running:

```bash
docker compose exec rag-service python evaluation/evaluate.py \
  --dataset evaluation/questions.local.json \
  --output evaluation/report.local.json \
  --min-source-hit 0.80
```

The report contains:

- `source_hit_at_k`: expected source appears among the first three returned sources.
- `answer_keyword_match_rate`: all expected answer terms are present.
- `refusal_accuracy`: unanswerable questions correctly receive a refusal.
- `source_backed_answer_rate`: a non-refusal answer returned at least one source.
- `latency_ms`: p50, p95, and mean end-to-end latency.

Use at least 30 production-like cases, including ambiguous wording, document-specific questions, and questions that should be refused. Do not add private datasets or generated reports to Git.

## Feedback review

Administrators can open the Feedback tab, review negative responses, and mark representative cases for evaluation. The Export selected action downloads `questions.candidates.json` from `/api/admin/feedback/evaluation-candidates`.

Review every exported case before adding it to `questions.local.json`: confirm the source documents and add verified `expected_answer_contains` facts. Candidates may include personal scopes, so keep the dataset local and do not commit it.
