# Reproduction guide

## Recalculate released results

```sh
python3 verify_release.py
python3 score_results.py
python3 check_consistency.py
```

These commands require Python 3.9 or newer and its standard library. They verify the file manifest; reconstruct 1,373 discovery labels from two independent reviewer tables and fourteen human choices; recalculate discovery statistics and review-stage agreement; check discovery screening; and validate recorded 160-check engineering and 104-scenario workflow outcomes.

The calculation uses retained observations. It does not repeat literature retrieval, model reviews or product execution.

Consistency checks also derive question sets from candidate identities, bind every current case to its original definition and observation, reconcile author processing with the complete replay record, and distinguish screening events from unique excluded candidates. Historical stage inputs are explicitly separated from the current scope in `protocols/release_definition.json`.

## Execute engineering and workflow checks

Obtain a source-only checkout of `LKong92/Gewu-Insight` at commit `539d00dd1a3b0f5857912223868ca232d56680c9`, under its access and licensing terms. `provenance/product_snapshot.json` lists the 393 tracked source files and their hashes. Use macOS and a dedicated CPython 3.9 environment; install the product dependencies and `requirements-replay.txt`.

```sh
python3 replay.py --task B \
  --product-source /absolute/path/to/frozen-source \
  --output-root /absolute/path/to/new-b-output

python3 replay.py --task C \
  --product-source /absolute/path/to/frozen-source \
  --output-root /absolute/path/to/new-c-output
```

B executes 160 engineering checks. C executes 52 retained and 52 current workflow scenarios. The optional `--production-root` marks an existing production checkout as forbidden. `--prepare-only` verifies source bytes and prepares a fresh run without execution. The wrapper rejects existing or overlapping output directories and active data-bearing source roots. Only manifest-listed product files are copied; writes and databases are restricted to the disposable run. External network access is disabled, with ephemeral loopback services allowed for isolated interface checks.

Each output directory receives its own `REPLAY_RESULT.json`. New results never overwrite the historical `results/` directory. Native Finder aliases and application interfaces are platform-specific; other-platform equivalence is not claimed.

The runners retain their execution-stage flags. Those flags do not adopt a new run as the publication result. The published adoption map is `results/execution_status.json`; see the stage-marker explanation in `DATA_DICTIONARY.md`. Updating the current coverage file changes descriptive scope and traceability links, while preserving scenario IDs, executable inputs, expectations and variant descriptions.

## Packaging and discovery inputs

Portable paths and a fresh harness lock replace machine-specific paths. Scenario IDs, inputs, observations and assertions remain traceable to their originals. An original synthetic analysis-text fixture and descriptive prose have presentation adaptations recorded by the export mapping. The discovery sampling helper reports discovery question counts for this release. These packaging adaptations do not modify product behavior or historical answer objects.

The release includes discovery metadata, selection probabilities, screening decisions, source indexes and review records. Product-level discovery replay additionally requires archived acquisition responses, and literature reinspection requires the original source evidence. These materials are retained separately; do not substitute a current web response for a historical input.

## Review history

The base discovery comparison is 1,225/1,263 initially and 1,251/1,263 after common evidence supplements and scoped corrections, before human adjudication. The corresponding broad-topic comparisons are 100/110 and 108/110. Twelve and two residual disagreements map exactly to the human choice records. Shared uncertainty remains unresolved. Intermediate snapshots retain the same discovery question identities.

Reviewers were Codex (GPT-6 Astra) and DeepSeek V4.1 Flash Max. DeepSeek Harness was the client. Their identity records and independence metadata are in `provenance/`.

## Download validation

Compare the release ZIP with `SHA256SUMS.txt`, extract it into a new directory, and run the three commands above. Original controlled source archives have separate hashes; their byte identity is not inferred from the released manifest.

For a local package comparison, run `python3 verify_package.py /path/to/Gewu-Insight-Evaluation.zip /path/to/SHA256SUMS.txt` from the corresponding repository checkout. It requires the ZIP to contain exactly the checkout's manifested files plus the manifest, with identical bytes and no duplicate paths. The published tag, repository tree and attached ZIP refer to the same prepared files.

## Reproduce the human-review comparison

Run `python3 verify_human_review.py` to reconstruct the eligible sampling frame from the accepted model answers and earlier adjudication records, reproduce the fixed-seed selection and display order, and compare the 60 final human choices with the accepted model consensus. This check is also included in `check_consistency.py`.

The eligible frame has 145 journal, 99 topic and 163 author candidates. Ten candidates are selected from each channel without replacement. The selection unit is a monitor-work candidate record. The report counts 30 sampled candidates and 60 field-level judgments; it does not treat the two topic fields as separate sampled papers. Source-material hashes identify archived inputs rather than a fresh online retrieval.
