# Human review

Human review covered a stratified sample of **30 discovery candidates**, comprising **60 field-level judgments**. The final human judgments agreed with the two-model consensus in all 60 comparisons. All 30 sampled candidates had agreement across their reviewed fields.

| Channel and field | Sampled candidates | Judgments agreeing with consensus | Human yes / no / uncertain |
|---|---:|---:|---:|
| Journal membership | 10 | 10/10 | 10 / 0 / 0 |
| Journal publication window | 10 | 10/10 | 10 / 0 / 0 |
| Journal research eligibility | 10 | 10/10 | 9 / 1 / 0 |
| Strict topic relevance | 10 | 10/10 | 7 / 3 / 0 |
| Broad topic relevance | 10 | 10/10 | 9 / 1 / 0 |
| Target-author attribution | 10 | 10/10 | 9 / 1 / 0 |

The three journal fields concern the same ten candidates, and the strict and broad topic fields concern the same ten candidates. Together with ten author candidates, these constitute 30 sampled records. Agreement includes agreement on negative labels; it is not a count of candidates satisfying every condition.

## Sampling and assessment

The sampling frame comprised candidates with agreement between the accepted Codex and DeepSeek judgments in every base field and, for topic candidates, broad relevance. Candidates with prior human adjudication on any field were excluded. Shared uncertain judgments remained eligible. This yielded 145 journal, 99 topic and 163 author candidates.

Ten records per channel were selected without replacement using the fixed-seed SHA-256 ranking specified in the [protocol](../protocols/human_review_protocol.json). Selection used candidate IDs rather than answer values, perceived difficulty or product outcomes. Each selected candidate had a probability of 10/145, 10/99 or 10/163 within its channel. The sampling unit was a monitor-work candidate record, not necessarily a globally unique paper.

L.K. reviewed the provided source materials and recorded yes, no or uncertain choices through the review interface. The field scope followed the existing base and broad-topic rubrics. Responses were choice-only; written rationales and item-level reading locations were not collected. The released answers are the final confirmed human judgments.

## Data and reproduction

The [sample](../data/human_review_sample.json) links each response to its candidate and provided source materials. The [final choices](../data/reviews/human_review.json) and [comparison](../results/human_review_summary.json) permit direct reconstruction of the reported agreement. Source bytes remain in the controlled literature archive, with identifiers and hashes supplied in the package.

Run `python3 verify_human_review.py` from the repository root. It reconstructs the eligible frame, fixed-seed selection, display order and field-level comparisons. This human review supplements the existing evaluation; the reference labels and all earlier AI, adjudication and product-execution records remain unchanged.
