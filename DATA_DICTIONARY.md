# Data dictionary

All files are UTF-8. JSON is the canonical release format. Stable identifiers preserve source-to-release correspondence.

| File or field | Meaning |
|---|---|
| `data/cases.json` | 421 discovery cases, each with membership, date and research-eligibility questions |
| `data/broad_questions.json` | One broad-topic question for each of the 110 topic candidates |
| `data/discovery_candidates.json` | Candidate title, axis, monitor, date window, inclusion probability and final field labels |
| `data/selected_units.json` | 493 monitor-work units selected before screening |
| `data/exclusions.json` | 84 historical screening events concerning 72 unique discovery candidates |
| `data/screening_current.json` | One row per excluded candidate, linked to every corresponding event |
| `data/sampling.json` | Current sampling counts, question counts and all three unresolved fields |
| `data/author_roster.json` | Current roster of 24 configured authors |
| `data/author_processing_status.json` | Processing evidence for the roster, occurrence counts and final panel representation |
| `protocols/release_definition.json` | Authoritative scope and frozen-version identity for this publication |
| `harness/protocol/workflow_coverage.json` | Current executable coverage linked to definitions and observations |
| `harness/config/task_b_cases.json` | Engineering definitions, linked to unchanged historical definitions and observed status |
| `results/execution_status.json` | Per-case adoption map for 160 engineering and 104 workflow observations |
| `provenance/stage_inputs/` | Unchanged historical case specification and pre-acquisition author roster |
| `provenance/publication_preparation.json` | Preserved-file hashes, preparation boundaries and superseded-manifest archive pointers |
| `data/reviews/{codex,deepseek}_{base,broad}.json` | Accepted pre-human decisions: 1,263 base and 110 broad records per reviewer |
| `data/reviews/initial/` | Initial decisions for the same discovery fields |
| `data/reviews/history/` | Available scoped-repair and evidence-supplement snapshots |
| `data/reviews/human_{base,broad}.json` | Twelve base and two broad actual human choices |
| `data/reference.json` | 1,373 final labels, with consensus or human-adjudication provenance |
| `data/unresolved_items.json` | Three unresolved fields and their evidence gaps |
| `data/evidence_catalog.json` | Source identifiers, URLs, checksums and controlled-archive locations |
| `results/runs/b160-001/observations.json` | 160 engineering expectations and observations |
| `results/runs/c-retained-001/observations.json` | 52 workflow observations |
| `results/runs/c-current-001/observations.json` | 52 further workflow observations |
| `results/agreement_history.json` | Recomputed discovery-only comparisons for each retained review stage |
| `question_id` | Stable discovery case ID followed by its field suffix |
| `label` | `yes`, `no` or `uncertain` |
| `confidence` | The reviewer's confidence; not calibrated between models or used as a human-task threshold |
| `assessment_status` | `determinate`, `not_assessable` or `substantive_ambiguity`, where supplied |
| `uncertainty_cause` | Explicit evidence, identity, source-conflict or rule-boundary cause |
| `source_claims` | Evidence IDs, fact IDs, original field identifiers and citation locations |
| `raw_value_sha256` | Hash of the original canonical JSON value |
| `original_answer_sha256` | Hash of the complete source answer object |
| `source_record_sha256` | Hash of the source file from which the released record was projected |
| `inclusion_probability` | Probability for the recorded selection stratum |
| `joint_label` | `no` if any required field is no; otherwise uncertain if any is uncertain; otherwise yes |

## Statistics

Screening counts candidates by unique `case_id`, not by event rows. The 493 selected monitor-work units include 72 unique excluded candidates and 421 retained candidates. There are 84 exclusion events because 12 candidates each have two stage records; all other excluded candidates have one. `data/screening_current.json` retains every event index without treating repeated events as new candidates. A candidate is a monitor-work unit, so this is not a claim of 421 globally distinct papers.

Confirmed panel proportion is yes/N. Unresolved-label identification bounds are [yes/N, (yes + uncertain)/N]. Weighted bounds use inverse inclusion probabilities. Author attribution is reported separately from date/type compliance. Strict and broad topic relevance use the same 110 candidates.

Agreement is exact equality of labels, including shared uncertainty. Cohen's kappa uses the observed agreement and full label marginals. Human choices are applied after the accepted pre-human comparison.

## Definitions, observations and adopted status

Current definitions and execution status are separate from historical stage metadata. The original engineering specification under `provenance/stage_inputs/` says `specified_not_formally_run` and `not_run` because it preceded execution. Its case identities, inputs, expected values and contracts are preserved in the executable definitions. Every current case links to its actual executed observation and the adoption map.

Raw observation and generator fields such as `formal_result=false` and `scores_authorized=false` describe the execution stage before final scoring authorization. They are retained unchanged. `provenance/single_version_validation.json` records completion; `results/execution_status.json` derives each adopted result from the corresponding observation. The `not_complete_104_workflows` marker in the retained-workflow file describes that file's 52-scenario scope; its companion supplies the other 52. A replay creates new observations, not automatic replacement publication results.

The original author roster's `pending_verified_profile_id` marker belongs to pre-acquisition selection. The later frozen-product replay reports all 24 profiles processed successfully. Current processing status cites that complete aggregate record; it does not invent provider IDs or claim a fresh live acquisition. Final candidates represent 22 authors. `by_author` reports occurrence counts; an absent author has zero occurrences in the complete aggregate, independently of processing success.

Additional product regression and platform probes remain supporting records under `results/runs/`. Their totals are separate from the headline engineering and workflow denominators.

## Hashes

`MANIFEST.json` covers every release file except itself. Source byte hashes and released byte hashes have distinct meanings; both are retained in export provenance. Canonical JSON uses sorted keys, UTF-8, compact separators and no trailing newline. File hashes use exact bytes.
