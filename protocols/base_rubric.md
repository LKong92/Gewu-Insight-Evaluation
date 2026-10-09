# Base review rubric

This common base review rubric defines the evaluation criteria. It describes the discovery rules applied to 421 cases and 1,263 questions on software commit `539d00dd1a3b0f5857912223868ca232d56680c9`. Original section numbers are retained for compatibility with reviewer citations. Original rubric bytes and revision history remain identified in provenance. The two reviewers received the same evidence and answered independently. Product observations and the other reviewer's answers were excluded from their review material.

## 1. Identify the exact work before using metadata

Candidate descriptions are objects to verify, not answers. Mechanical reading aids and exact-string DOI/title matches are navigation aids. A matching DOI with a contradictory title still requires explanation. Without a DOI, jointly check full title, authors, venue, year and version. The first search result, a similar title, a neighbouring item or a cited reference cannot supply the candidate's metadata. Failure to bind a source is an evidence gap, not proof that the candidate itself is ineligible.

## 2. Author and journal membership

Evaluate the named researcher without an extra subject-area filter. Link an official identity or researcher identifier to the work's authorship. Standard transliterations, accents and initials can be resolved using affiliations, coauthors and identifiers; spelling variation alone need not imply uncertainty. A truncated author list cannot establish absence. A verified Scholar profile establishes profile identity, not the correctness of every work returned from it. Journal membership must come from the matching publication record, not the query or product label.

## 3. Publication-window membership

Identify the document object and inclusive window first. Independently registered preprints and journal publication are different events; apply section 22 to repository copies and supplements. Use the first explicit online publication date, otherwise print. Created, indexed, deposited, citation dates, access times, project numbers and reference years are not publication dates. A generic publication_date does not become online-first by renaming it.

Prioritize explicit publisher dates for the exact work, then correctly matched typed Crossref/arXiv dates, with typed dates from other records as supplements. Untyped dates have lower priority. Record genuine contradictions within higher-priority sources. If all credible interpretations lie inside the window, or all outside, exact calendar disagreement need not prevent yes/no; retain the discrepancy in the reasoning. A supported unresolved interpretation crossing the boundary requires uncertainty.

Use the supported interval at the actual precision. A year alone spans that year; 2026 cannot establish inclusion in January–September 2026. A whole month contained in the window can establish inclusion. Do not invent month/day precision or a date type.

## 4. Strict topic relevance and research-document type

Apply each topic's include/exclude definition to the complete available abstract or relevant body. Explain how the primary research problem satisfies or violates the boundary. Search hits, keywords and database subject labels are not enough. Downstream use of a method does not automatically satisfy a topic requiring a contribution to that method. Insufficient content remains uncertain.

Eligible research documents include original research, reviews, methods, analyses, theory and substantive research perspectives. Explicit type or actual research question/method/result/synthesis can support inclusion without requiring both PDF and full text. Generic article/journal-article metadata alone cannot turn news, editorials, book reviews, promotional material or standalone notices into research. Conversely, clear research content does not require an exact "research article" label.

## 5. Uncertainty and confidence

Labels state what the evidence supports. Confidence concerns the chosen label, is not cross-model calibrated and does not set human workload. A reviewer may confidently conclude that evidence is insufficient. Use `determinate` for a definite answer; `not_assessable` for missing evidence or unresolved identity; `substantive_ambiguity` for adequate material with unresolved same-priority conflict or a genuine rule boundary. Uncertain answers require the corresponding cause. Keep exact evidence and location. Do not bulk-label unread cases or inspect another reviewer's directory.

## 6. Synthetic self-checks

A typed April online date and a generic May date both inside March–June do not automatically conflict. A year-only date cannot establish inclusion in a half-year window. Absence from a truncated author list does not prove absence from the full list. A project number or citation count is not a year. A similar but different work cannot lend its date. Drug-design research using predicted structures is judged against the stated strict-topic boundary. A clear experimental abstract can establish research type without a PDF. Two unexplained same-priority online dates on opposite sides of the window create a genuine conflict.

## 7. Keep the three A fields separate

Membership concerns journal, topic or named researcher; date concerns the applicable publication event; research eligibility concerns document type. A non-research document may still have genuine target authorship. A no or uncertain in one field does not determine the others. Every fact must preserve its work/version object, evidence ID, exact locator, original field and value. Empty source values remain empty. Do not fill a blank Scholar year from neighbouring rows, project numbers or citation plots. Completeness of an author list needs support; absence of a truncation warning is not proof of completeness. Identify the link between the researcher and authorship rather than reasoning circularly from the search profile.

## 8. Submission self-check

Evidence must be recoverable at the named source and locator. Date answers retain type and field name; authorship answers state identity binding; topic answers cite content and scope; type answers cite specific type or substantive content. Determinate answers use a null uncertainty cause. Missing evidence/identity use not_assessable; genuine same-priority conflict/boundary use substantive_ambiguity. Format validation is not scientific validation.

## 9. Shared document-scope clarification

Include complete research papers, reviews, methods/analysis/theory papers, substantive research perspectives and full conference papers. Exclude conference abstracts, posters, schedules/promotional records, theses and patents, as well as news, editorials, book reviews and independent notices. Page count does not distinguish a short paper from an abstract. A DOI or reported result does not turn a meeting abstract into a full conference paper. Research preprints remain eligible by substantive content. Dataset records alone are not research articles; substantive Data Descriptor papers can qualify.

Supervisors, reading-committee members, chairs, attendees and acknowledged people are not automatically authors. Preserve inventor roles in patent records; invention attribution does not establish paper authorship or research-document eligibility. For presentations, verify the named presenter, not the entire conference roster. Keep conference versions, preprints, journal editions, theses and patent versions distinct. Patent priority, application-publication and grant dates are different events. Meeting dates or degree years do not by themselves prove first public availability.

## 10. Source reading and precise fields

Start with the exact citation_for_view key, DOI or arXiv identifier. Keep Scholar title, author line, venue line, year and citation count separate. A specific item category, such as News & Views, Correspondence or Correction, takes precedence over generic page-template type; apply content rather than category name alone where substance matters. Read this item's authors, date and abstract, not references, recommendations, sidebars or copyright year. Manuscript-template placeholders are not real identifiers or dates. HTTP 200 may still be a challenge, login, error or unrelated page. Use one-based physical PDF pages, optionally also printed pages, and exact HTML/JSON locations.

## 11. Fact cards and shared corrections

Mechanical fact cards are not answers. A citation_online_date remains a page-declared online date whose object must be checked; it may describe an arXiv revision. Preserve registered fact IDs, source IDs, locators, field names, raw values, objects and semantic types. Unregistered source passages may be read and cited. Record extraction errors as evidence issues; corrected material must be supplied symmetrically, rather than privately fetching evidence for one reviewer. There is no target agreement rate or confidence threshold that automatically creates a human task.

## 12. Additional synthetic checks

A reading-committee member is not a thesis coauthor. A named inventor and patent research eligibility are separate questions. A generic BriefCommunication template does not erase an explicit News & Views designation. A title appearing at two conferences must be bound to the exact candidate event. A browser-verification page is not article evidence.

## 13. Explicit preprint fields

Crossref posted-content `posted` differs from `created`. Retain its version meaning; revision evidence can prevent treating it as first-version submission. Preserve publisher assertion name, label and value; "Published" alone does not automatically mean online-first. Resolve work/version relationships before combining dates from different identifiers.

## 14. Date scope within repositories and files

A repository citation_online_date is not automatically journal online-first. Compare displayed bibliographic information, the publisher and exact DOI registration. Preserve repository release/update events separately. Advertisements, covers, download stamps, copyright years and adjacent Received/Revised dates cannot fill an empty Published online value. Establish supplement-to-article correspondence using DOI, title, authors and the explicit publisher link. Section 22 then governs the article's publication window without claiming simultaneous binary-file upload.

## 15. Correspondence indexes and date labels

Organizer correspondence indexes record source relationships and verbatim locations, not answers. Related/conflicting records require source inspection. Publisher headline dates may be acceptance or issue dates; inspect labelled article history. Patent pages contain multiple date fields for families and cited patents; bind the exact candidate identifier. A correction may share the original title/authors but differ in DOI/pages. A registration abstract may be editorial text discussing more than one work; do not attribute another work's results to the candidate.

## 16. Original fields versus reading aids

Crossref author, OpenAlex authorships and Semantic Scholar authors are different original fields. Retain explicit truncation markers and original abstract markup/inverted indexes. Reconstructed text and normalized names are aids, not original fields. JSON root has an empty pointer; child fields use their real pointers. A parent-object locator does not prove a specific field was checked.

## 17. arXiv and peer-review records

Use namespace-aware Atom entry locations. `atom:published` is first submission; `atom:updated` is revision. Journal DOI/reference points to a different publication event. Do not derive dates from identifier months. Referee reports, author replies and reviewed papers are distinct documents. Preserve peer-review type, review subtype and is-review-of relationships. An attached research abstract is not automatically the report/reply body; a review article is not a referee report.

## 18. Scholar details and merged entries

Read the detail page for the exact original citation key. No displayed Publication date means that page did not supply it; citation-chart years cannot fill the gap. Scholar may merge or link different works, whose fields must not be transplanted. Details aid identification but do not turn supervisors into authors. An untyped Publication date is not online-first.

## 19. Screening boundary

The retained case list defines review scope. Known excluded types have itemized records. Full conference papers and substantive Data Descriptor papers remain eligible. Missing evidence, inaccessible sources, truncated titles or unknown types are not automatic general deletion rules. Comments, Correspondence and Perspectives are judged on their own content. Screened-panel performance is not raw-output population precision.

## 20. Specific user-directed exclusions

Six named old objects and twelve unlocated objects from the 83-item author expansion were explicitly excluded by the user; fifteen expansion objects were excluded under the shared type scope. These decisions do not authorize reviewers to delete other cases, do not imply type verification for unlocated items and are not evidence-repair successes or product passes. An additional documented shared scope correction excluded one explicit conference abstract, with no replacement. The release includes the complete screening ledger.

## 21. Temporal upper bounds and unsupported version assumptions

An authentic dated distribution record for the exact version can establish public availability no later than that date. Keep the original field and state that this is an upper bound, not a known first-publication day. An upper bound before the window can establish exclusion; one inside or after the window cannot establish first publication inside it. Verify exact DOI, title, version and physical page for historical publisher stamps. Current download times, file creation times and ordinary repository record creation cannot substitute. A misextracted template title does not establish an independent preprint. Publisher policy alone is not an item-specific date.

## 22. Correct publication object for A

A evaluates the candidate research document's publication window, not a PDF's first upload, download or repository embargo release. A verified repository accepted/submitted manuscript copy or publisher-linked supplement without an independent preprint identifier or separately published/revised identity uses the associated journal article's first explicit online date, otherwise print. The publication relationship must be established using identifiers and matching title/authors/content. A manuscript-stage label does not by itself create a new publication event. File role, authorship and research eligibility remain separate.

Independently registered arXiv/preprint DOIs, separate corrections/revisions and independent data publications use their own applicable events. Deposit, available, accessioned, created and metadata-import timestamps retain their meaning. A manuscript may predate publication yet enter a repository later. This correction was applied symmetrically before the current complete reassessment; it did not replace new AI answers with organizer labels.

## 23. Human-adjudication boundary

Only residual substantive disagreements after complete submissions and common field/source checks go to human choice. Low confidence, sentinel items, blanket audits and shared uncertainty do not automatically create human questions. Evidence gaps first return to material preparation. Model consensus is not human-validated gold. Preserve initial agreement and revisions.

## 25. Submission structure and exact records

Each base answer carries assessment_status, uncertainty_cause, source_claims, evidence and evidence_issues. Registered fact-card citations preserve all fields. PDF or unstructured source evidence may use physical page/paragraph and a short verbatim quote with an empty source_claims list. Exact record extracts retain original response hashes and positions; removing other search hits does not turn them into answers. Packet/material hashes bind the original rules, navigation, questions and evidence.

## 27. Candidate-specific research eligibility

Judge whether the candidate itself is a complete research document, not whether it contains any research details. Verified attached supporting information is not a standalone complete paper merely because its parent qualifies. Complete accepted/submitted manuscripts and research preprints can qualify without typesetting. Determine role from evidence, not only words in titles. A contents page is distinct from papers it lists. Authorship and section-22 publication date remain separate. This shared clarification was recorded after returns and applied to both reviewers; later answers are not represented as first-pass answers.

## 28. Complete reading versus evidence insufficiency

A truncated product candidate is the tested input, not proof that the original publication truncates the same field. Read the full matching source and complete field inventory; pagination markers indicate more content. Mechanical search cannot establish authorship or list completeness. Inspect all relevant pages when notices share a page or manuscripts carry extra covers. Text extraction cannot establish images, annotations, layout or scanned text: inspect the actual file when these matter. Before not_assessable, record what was read and the necessary remaining gap. Source conflict after adequate reading is not absence of material. Read all questions, including previously determinate ones, without an agreement or uncertainty-reduction target.

## Later scoped evidence supplements

Subsequent shared evidence and identity supplements retained the same field definitions, exact question scope and independent-review restrictions. Each reviewer carried forward its own baseline and changed only authorized questions. Intake checks verified unchanged out-of-scope objects, packet bindings and new review records. No supplement guaranteed a changed label or determinate answer. The accepted result retains two unresolved author-identity questions; final human adjudication concerned twelve other base questions. Historical and final decisions remain separately identified.
