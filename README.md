# Gewu Insight Evaluation

Research data and reproducibility materials for *A Stateful Research Information Infrastructure for Scientific Discovery*.

The evaluation uses frozen software commit `539d00d`, schema 22. Complete revision and file hashes are recorded in [product provenance](provenance/product_snapshot.json).

## Results

| Component | Result | Meaning |
|---|---:|---|
| Journal discovery | 137/145 (94.48%) | Journal, publication window and eligible document type jointly satisfied |
| Author attribution | 156/166 (93.98%) | Exact target-author attribution; 8 negative, 2 unresolved |
| Strict topic relevance | 78/110 (70.91%) | Topic is a primary research concern |
| Broad topic relevance | 104/110 (94.55%) | Substantive core, application, review or mechanistic connection; 5 negative, 1 unresolved |
| Engineering checks | 160/160 | Ten synthetic-test families |
| Persistent workflows | 104/104 | Twenty-six families, four variants each |

The discovery panel contains **421 candidates**: 145 journal, 110 topic and 166 author candidates. All 24 configured author profiles were reprocessed successfully; the final panel represents 22 authors and six of eight configured topics.

Codex (GPT-6 Astra) and DeepSeek V4.1 Flash Max independently assessed **1,263 base discovery fields** and **110 broad-topic fields** each. Initial agreement was 1,225/1,263 (96.99%) and 100/110 (90.91%). After shared evidence supplementation and scoped corrections, agreement before human adjudication was 1,251/1,263 (99.05%) and 108/110 (98.18%). Fourteen human choices resolved the remaining evaluable disagreements. Three fields remain explicitly uncertain. The reference contains 1,373 judgments.

Human review covered a stratified sample of **30 discovery candidates** (10 journal, 10 topic and 10 author candidates), comprising **60 field-level judgments**. The final human judgments agreed with the two-model consensus in all 60 comparisons. The [human-review report](reports/human_review.md) provides the sampling method and results.

Journal discovery uses a September 2026 window; topic and author candidates use January–September 2026. The reported proportions describe the evaluated panel. Original date/type and joint-condition measurements, sampling probabilities and reporting amendments are retained in the data and provenance. Discovery observations were replayed from preserved source responses through the frozen software.

## Verify and use the data

Python 3.9 or newer and its standard library suffice:

```sh
python3 verify_release.py
python3 score_results.py
python3 check_consistency.py
```

These commands verify released bytes, reconstruct the reference from both reviewers and human choices, recalculate results, reproduce the human-review sample and agreement, and check consistency across the release.

The [release definition](protocols/release_definition.json) identifies the current scope. [Execution status](results/execution_status.json) links each engineering and workflow case to its preserved observation. The [data dictionary](DATA_DICTIONARY.md) explains historical stage markers and discovery-screening events.

| Directory | Contents |
|---|---|
| `data/` | Discovery cases, source catalog, sampling and screening records, independent decisions and human choices |
| `protocols/` | Review rubrics, review policy, acquisition and sampling design |
| `results/` | Discovery statistics, agreement history and recorded engineering/workflow observations |
| `harness/` | Engineering/workflow runners, synthetic fixtures and discovery reconstruction tools |
| `provenance/` | Frozen software hashes, reviewer identity, record projection and source-to-release mapping |
| `reports/` | Methods and results text |

See [REPRODUCTION.md](REPRODUCTION.md), [DATA_DICTIONARY.md](DATA_DICTIONARY.md) and [RELEASE_SCOPE.md](RELEASE_SCOPE.md). Product source and third-party full-text documents are separate dependencies.

## Citation and data availability

The [evaluation release](https://github.com/LKong92/Gewu-Insight-Evaluation/releases/tag/evaluation-20261010) provides the ZIP and SHA-256 checksum. Citation metadata are in [CITATION.cff](CITATION.cff); manuscript wording is in [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md).
