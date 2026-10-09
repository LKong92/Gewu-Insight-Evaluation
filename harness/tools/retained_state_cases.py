from __future__ import annotations
# Engineering requirements retained from the source implementation.
# See config/retained_code_provenance.json. Product imported unchanged at runtime.
import argparse, contextlib, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from paper_monitor import ui_server
from paper_monitor.importers.inventory import build_existing_index, existing_paper_id
from paper_monitor.resource_fingerprint import fingerprint_file
from paper_monitor.storage import STORAGE_SCHEMA_VERSION, Storage
from paper_monitor.text import make_paper_id
from state_support import *
LEGACY_COMMITS = ["b509539", "99c3b67", "5073faf", "113e2b2"]


STATE_VARIANTS: dict[str, tuple[dict[str, Any], ...]] = {
    "C01_three_entry_same_work": (
        {"structural_variant": "canonical_doi_across_three_axes", "code_path_tags": ["c01:v1:exact_doi_canonical", "c01:v1:doi_resolver_for_later_axes"]},
        {"structural_variant": "arxiv_revision_then_doi_enrichment", "code_path_tags": ["c01:v2:arxiv_revision_normalization", "c01:v2:inventory_identifier_enrichment"]},
        {"structural_variant": "scholar_title_only_then_identifier_enrichment", "code_path_tags": ["c01:v3:scholar_title_year_match", "c01:v3:doi_enrichment_after_title_only"]},
        {"structural_variant": "canonical_doi_then_scholar_only_enrichment", "code_path_tags": ["c01:v4:stored_canonical_doi", "c01:v4:scholar_only_existing_resolution"]},
    ),
    "C02_preprint_to_vor": (
        {"structural_variant": "preprint_then_vor", "code_path_tags": ["c02:v1:preprint_then_download", "c02:v1:single_prior_lineage"]},
        {"structural_variant": "preprint_revision_chain_then_vor", "code_path_tags": ["c02:v2:multiple_preprints", "c02:v2:latest_prior_lineage"]},
        {"structural_variant": "metadata_refresh_between_versions", "code_path_tags": ["c02:v3:publisher_metadata_refresh", "c02:v3:title_change_before_download"]},
        {"structural_variant": "vor_then_late_preprint", "code_path_tags": ["c02:v4:reverse_arrival_order", "c02:v4:late_preprint_no_displacement"]},
    ),
    "C03_accepted_to_published": (
        {"structural_variant": "accepted_then_published", "code_path_tags": ["c03:v1:accepted_then_vor", "c03:v1:direct_lineage"]},
        {"structural_variant": "preprint_accepted_published", "code_path_tags": ["c03:v2:three_version_roles", "c03:v2:accepted_lineage_target"]},
        {"structural_variant": "duplicate_accepted_source_then_published", "code_path_tags": ["c03:v3:accepted_exact_dedupe", "c03:v3:publisher_after_duplicate"]},
        {"structural_variant": "published_then_late_accepted", "code_path_tags": ["c03:v4:late_accepted_arrival", "c03:v4:vor_rank_preserved"]},
    ),
    "C04_byte_identical_refresh": (
        {"structural_variant": "same_filename_manual_reupload", "code_path_tags": ["c04:v1:manual_attach_same_name", "c04:v1:exact_duplicate_repeat"]},
        {"structural_variant": "renamed_source_manual_reupload", "code_path_tags": ["c04:v2:manual_attach_renamed", "c04:v2:exact_hash_over_filename"]},
        {"structural_variant": "forced_download_identical_refresh", "code_path_tags": ["c04:v3:download_snapshot_register", "c04:v3:download_exact_reuse"]},
        {"structural_variant": "publisher_duplicate_repairs_preprint", "code_path_tags": ["c04:v4:publisher_download_attach", "c04:v4:duplicate_role_repair"]},
    ),
    "C05_clean_annotated_same_content": (
        {"structural_variant": "clean_then_annotated_immediate", "code_path_tags": ["c05:v1:clean_first", "c05:v1:no_fingerprint_refresh"]},
        {"structural_variant": "annotated_then_clean_immediate", "code_path_tags": ["c05:v2:annotated_first", "c05:v2:second_attach_relation"]},
        {"structural_variant": "clean_annotated_explicit_refresh", "code_path_tags": ["c05:v3:clean_first_refresh", "c05:v3:fingerprint_recompute"]},
        {"structural_variant": "annotated_clean_manual_role_repair", "code_path_tags": ["c05:v4:annotated_first_reclassify", "c05:v4:manual_annotation_role"]},
    ),
    "C06_nonpublication_never_current": (
        {"structural_variant": "manual_preferred_supplement_then_auto_restore", "code_path_tags": ["c06:v1:manual_preferred_supplement", "c06:v1:auto_secondary_exclusion"]},
        {"structural_variant": "manual_preferred_other_pdf_then_auto_restore", "code_path_tags": ["c06:v2:manual_preferred_other_pdf", "c06:v2:auto_secondary_exclusion"]},
        {"structural_variant": "manual_preferred_note_then_auto_restore", "code_path_tags": ["c06:v3:manual_preferred_note", "c06:v3:auto_secondary_exclusion"]},
        {"structural_variant": "automatic_selection_without_manual_attempt", "code_path_tags": ["c06:v4:auto_rank_only", "c06:v4:no_preference_mutation"]},
    ),
    "C07_manual_preferred_then_auto": (
        {"structural_variant": "prefer_preprint_then_clear", "code_path_tags": ["c07:v1:manual_preprint_swap", "c07:v1:auto_restore_vor"]},
        {"structural_variant": "prefer_accepted_then_clear", "code_path_tags": ["c07:v2:manual_accepted_swap", "c07:v2:auto_rank_over_accepted"]},
        {"structural_variant": "prefer_current_vor_then_clear", "code_path_tags": ["c07:v3:manual_current_noop", "c07:v3:clear_same_primary"]},
        {"structural_variant": "preference_blocks_new_vor_until_clear", "code_path_tags": ["c07:v4:preferred_lock_during_arrival", "c07:v4:new_vor_after_clear"]},
    ),
    "C08_multiple_roots": (
        {"structural_variant": "two_library_folders", "code_path_tags": ["c08:v1:library_library", "c08:v1:folder_aliases"]},
        {"structural_variant": "library_and_space", "code_path_tags": ["c08:v2:library_space", "c08:v2:cross_root_aliases"]},
        {"structural_variant": "library_and_my_publications", "code_path_tags": ["c08:v3:library_publications", "c08:v3:publication_alias"]},
        {"structural_variant": "two_spaces_and_my_publications", "code_path_tags": ["c08:v4:space_space_publications", "c08:v4:no_library_item"]},
    ),
    "C09_scoped_relation_deletion": (
        {"structural_variant": "delete_one_library_shortcut", "code_path_tags": ["c09:v1:library_item_delete", "c09:v1:other_associations_retained"]},
        {"structural_variant": "delete_author_monitor_relation", "code_path_tags": ["c09:v2:author_monitor_cascade", "c09:v2:library_relations_retained"]},
        {"structural_variant": "delete_my_publication_relation", "code_path_tags": ["c09:v3:publication_delete", "c09:v3:monitor_relations_retained"]},
        {"structural_variant": "delete_nonprimary_file_relation", "code_path_tags": ["c09:v4:resource_delete", "c09:v4:primary_file_retained"]},
    ),
    "C10_move_rename_repair_restart": (
        {"structural_variant": "managed_folder_move_only", "code_path_tags": ["c10:v1:library_move", "c10:v1:alias_resync"]},
        {"structural_variant": "managed_item_rename_only", "code_path_tags": ["c10:v2:library_rename", "c10:v2:associated_dir_relabel"]},
        {"structural_variant": "managed_move_then_rename", "code_path_tags": ["c10:v3:move_and_rename", "c10:v3:managed_path_remap"]},
        {"structural_variant": "external_rename_then_path_repair", "code_path_tags": ["c10:v4:external_filesystem_rename", "c10:v4:explicit_pdf_path_repair"]},
    ),
    "C11_invalid_failure_recovery": (
        {"structural_variant": "html_masquerade_then_recovery", "code_path_tags": ["c11:v1:html_header_rejection", "c11:v1:valid_retry"]},
        {"structural_variant": "empty_upload_then_recovery", "code_path_tags": ["c11:v2:empty_payload_rejection", "c11:v2:valid_retry_after_empty"]},
        {"structural_variant": "truncated_pdf_header_then_recovery", "code_path_tags": ["c11:v3:header_only_acceptance_audit", "c11:v3:recovery_after_product_failure"]},
        {"structural_variant": "late_pdf_marker_boundary_then_recovery", "code_path_tags": ["c11:v4:inspection_window_boundary", "c11:v4:valid_retry_after_boundary"]},
    ),
    "C12_schema10_nondestructive_migration": (
        {"structural_variant": "schema5_primary_backfill", "code_path_tags": ["c12:v1:schema5_missing_state_columns", "c12:v1:primary_resource_backfill"]},
        {"structural_variant": "schema6_nested_folder_backfill", "code_path_tags": ["c12:v2:schema6_nested_library", "c12:v2:my_publication_preserve"]},
        {"structural_variant": "schema7_existing_primary_preserve", "code_path_tags": ["c12:v3:schema7_existing_resource", "c12:v3:primary_pointer_preserve"]},
        {"structural_variant": "schema8_primary_and_supplement_preserve", "code_path_tags": ["c12:v4:schema8_multi_resource", "c12:v4:attachment_preserve"]},
    ),
    "C13_standalone_merge_and_rollback": (
        {"structural_variant": "single_file_successful_merge", "code_path_tags": ["c13:v1:single_resource_merge", "c13:v1:source_cleanup"]},
        {"structural_variant": "multi_file_successful_merge", "code_path_tags": ["c13:v2:multiple_resource_merge", "c13:v2:batch_source_cleanup"]},
        {"structural_variant": "shared_source_guarded_rollback", "code_path_tags": ["c13:v3:shared_item_guard", "c13:v3:preflight_rollback"]},
        {"structural_variant": "injected_second_move_rollback", "code_path_tags": ["c13:v4:mid_batch_failure", "c13:v4:filesystem_database_rollback"]},
    ),
}


STATE_REQUIRED_STEPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "C01_three_entry_same_work": (
        ("journal_ingestion", "subject_ingestion", "author_ingestion"),
        ("subject_ingestion", "journal_ingestion", "author_ingestion"),
        ("author_ingestion", "journal_ingestion", "subject_ingestion"),
        ("journal_ingestion", "author_ingestion", "subject_ingestion"),
    ),
    "C02_preprint_to_vor": (
        ("preprint_available", "version_of_record_download"),
        ("preprint_available", "later_preprint_revision", "version_of_record_download"),
        ("preprint_available", "publisher_metadata_refresh", "version_of_record_download"),
        ("version_of_record_first", "late_preprint_history"),
    ),
    "C03_accepted_to_published": (
        ("accepted_manuscript", "published_version"),
        ("preprint_before_acceptance", "accepted_manuscript", "published_version"),
        ("accepted_manuscript", "duplicate_accepted_source", "published_version"),
        ("published_version", "late_accepted_manuscript"),
    ),
    "C04_byte_identical_refresh": (
        ("initial_file", "byte_identical_manual_refresh", "idempotent_manual_rerun"),
        ("initial_file", "byte_identical_manual_refresh", "idempotent_manual_rerun"),
        ("initial_file", "byte_identical_forced_download_refresh", "idempotent_forced_download_rerun"),
        ("initial_file", "publisher_duplicate_role_repair", "publisher_duplicate_role_repair_rerun"),
    ),
    "C05_clean_annotated_same_content": (
        ("attach_clean", "attach_annotated"),
        ("attach_annotated", "attach_clean"),
        ("attach_clean", "attach_annotated", "explicit_fingerprint_refresh"),
        ("attach_annotated", "attach_clean", "manual_annotation_role_repair"),
    ),
    "C06_nonpublication_never_current": (
        ("primary_publication", "related_pdf", "non_pdf_attachment", "manual_preferred_secondary", "clear_manual_preference"),
        ("primary_publication", "related_pdf", "non_pdf_attachment", "manual_preferred_secondary", "clear_manual_preference"),
        ("primary_publication", "related_pdf", "non_pdf_attachment", "manual_preferred_secondary", "clear_manual_preference"),
        ("primary_publication", "related_pdf", "non_pdf_attachment", "automatic_selection_control"),
    ),
    "C07_manual_preferred_then_auto": (
        ("automatic_ranking", "manual_preference", "clear_manual_preference"),
        ("automatic_ranking", "manual_preference", "clear_manual_preference"),
        ("automatic_ranking", "manual_preference", "clear_manual_preference"),
        ("automatic_ranking", "manual_preference", "new_vor_arrived_under_manual_preference", "clear_manual_preference"),
    ),
    "C08_multiple_roots": tuple(
        ("root_associations_created", "primary_resource_attached", "multi_root_sync")
        for _ in range(4)
    ),
    "C09_scoped_relation_deletion": tuple(
        ("shared_relations_created", "resource_set_created", "shared_state_before_delete", "scoped_relation_delete")
        for _ in range(4)
    ),
    "C10_move_rename_repair_restart": (
        ("source_associations_created", "source_location", "move_to_target_folder"),
        ("source_associations_created", "source_location", "rename_and_sync"),
        ("source_associations_created", "source_location", "move_to_target_folder", "rename_and_sync"),
        ("source_associations_created", "source_location", "move_to_target_folder", "rename_and_sync", "external_rename_repair"),
    ),
    "C11_invalid_failure_recovery": tuple(
        ("failure_status_recorded", "invalid_pdf_rejected", "valid_retry_recovery")
        for _ in range(4)
    ),
    "C12_schema10_nondestructive_migration": tuple(
        ("product_opened_legacy_database",) for _ in range(4)
    ),
    "C13_standalone_merge_and_rollback": (
        ("standalone_objects_created", "standalone_before_merge", "standalone_merged"),
        ("standalone_objects_created", "standalone_before_merge", "standalone_merged"),
        ("standalone_objects_created", "shared_source_precondition", "standalone_before_merge", "shared_source_guard"),
        ("standalone_objects_created", "standalone_before_merge", "injected_atomic_failure"),
    ),
}


def variant_spec(
    family_id: str,
    variant: int,
    *,
    catalog: dict[str, tuple[dict[str, Any], ...]] | None = None,
) -> dict[str, Any]:
    variants = (STATE_VARIANTS if catalog is None else catalog).get(str(family_id))
    if variants is None:
        raise KeyError(f"No structural variants declared for {family_id}")
    if variant < 0 or variant >= len(variants):
        raise IndexError(f"Variant {variant} is not declared for {family_id}")
    spec = variants[variant]
    required_variants = STATE_REQUIRED_STEPS.get(str(family_id), ())
    if variant >= len(required_variants):
        raise IndexError(f"Required steps are not declared for {family_id} variant {variant}")
    return {
        "structural_variant": str(spec.get("structural_variant") or ""),
        "code_path_tags": [str(tag) for tag in spec.get("code_path_tags") or []],
        "required_steps": list(required_variants[variant]),
    }


def audit_state_variant_structure(
    families: list[dict[str, Any]],
    *,
    fixture_count: int = 4,
    catalog: dict[str, tuple[dict[str, Any], ...]] | None = None,
) -> dict[str, Any]:
    """Statically reject repeated or underspecified formal fixture variants."""

    selected = STATE_VARIANTS if catalog is None else catalog
    errors: list[str] = []
    family_audits: dict[str, Any] = {}
    scenario_ids = [str(family.get("id") or "") for family in families]
    if len(scenario_ids) != len(set(scenario_ids)):
        errors.append("scenario family ids are duplicated")
    undeclared = sorted(set(scenario_ids) - set(selected))
    extra = sorted(set(selected) - set(scenario_ids))
    if undeclared:
        errors.append(f"scenario families without variant declarations: {undeclared}")
    if extra:
        errors.append(f"variant declarations without scenario families: {extra}")
    missing_step_families = sorted(set(scenario_ids) - set(STATE_REQUIRED_STEPS))
    extra_step_families = sorted(set(STATE_REQUIRED_STEPS) - set(scenario_ids))
    if missing_step_families:
        errors.append(f"scenario families without required-step declarations: {missing_step_families}")
    if extra_step_families:
        errors.append(f"required-step declarations without scenario families: {extra_step_families}")
    for family_id in scenario_ids:
        variants = selected.get(family_id, ())
        names: list[str] = []
        tag_sets: list[tuple[str, ...]] = []
        all_tags: list[str] = []
        family_errors: list[str] = []
        required_variants = STATE_REQUIRED_STEPS.get(family_id, ())
        if len(variants) < fixture_count:
            family_errors.append(f"declares {len(variants)} variants, requires {fixture_count}")
        if len(required_variants) < fixture_count:
            family_errors.append(
                f"declares required steps for {len(required_variants)} variants, requires {fixture_count}"
            )
        for index, raw in enumerate(variants[:fixture_count]):
            name = str(raw.get("structural_variant") or "").strip()
            tags = [str(tag).strip() for tag in raw.get("code_path_tags") or []]
            if not name:
                family_errors.append(f"V{index + 1:02d} has no structural_variant")
            if not tags or any(not tag for tag in tags):
                family_errors.append(f"V{index + 1:02d} has empty code_path_tags")
            if len(tags) != len(set(tags)):
                family_errors.append(f"V{index + 1:02d} repeats a code_path_tag internally")
            names.append(name)
            tag_sets.append(tuple(sorted(tags)))
            all_tags.extend(tags)
            if index < len(required_variants):
                steps = list(required_variants[index])
                if not steps or any(not str(step).strip() for step in steps):
                    family_errors.append(f"V{index + 1:02d} has empty required_steps")
                if len(steps) != len(set(steps)):
                    family_errors.append(f"V{index + 1:02d} repeats a required step")
        duplicate_names = sorted({name for name in names if name and names.count(name) > 1})
        duplicate_sets = sorted({tags for tags in tag_sets if tags and tag_sets.count(tags) > 1})
        duplicate_tags = sorted({tag for tag in all_tags if tag and all_tags.count(tag) > 1})
        if duplicate_names:
            family_errors.append(f"repeated structural_variant values: {duplicate_names}")
        if duplicate_sets:
            family_errors.append(f"repeated code_path_tag sets: {duplicate_sets}")
        if duplicate_tags:
            family_errors.append(f"code_path_tags reused across variants: {duplicate_tags}")
        errors.extend(f"{family_id}: {message}" for message in family_errors)
        family_audits[family_id] = {
            "declared": len(variants),
            "audited": min(len(variants), fixture_count),
            "valid": not family_errors,
            "errors": family_errors,
            "variants": [variant_spec(family_id, index, catalog=selected) for index in range(min(len(variants), fixture_count))],
        }
    return {
        "valid": not errors,
        "fixture_count": fixture_count,
        "family_count": len(scenario_ids),
        "errors": errors,
        "families": family_audits,
    }


def require_state_variant_structure(
    families: list[dict[str, Any]],
    *,
    fixture_count: int = 4,
    catalog: dict[str, tuple[dict[str, Any], ...]] | None = None,
) -> dict[str, Any]:
    audit = audit_state_variant_structure(
        families,
        fixture_count=fixture_count,
        catalog=catalog,
    )
    if not audit["valid"]:
        raise RuntimeError("State variant structural audit failed: " + "; ".join(audit["errors"]))
    return audit


def current_benchmark_schema_version() -> str:
    return str(load_config()["schema_version"])


def jsonable_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in row.keys()} for row in rows]


def sqlite_snapshot(db_path: Path) -> dict[str, Any]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        selected: dict[str, Any] = {}
        for table, order in (
            ("papers", "paper_id"),
            (
                "paper_source_observations",
                "paper_id, source_kind, source_name, source_key, id",
            ),
            ("resources", "id"),
            ("library_folders", "id"),
            ("library_items", "id"),
            ("my_publications", "id"),
            ("theme_results", "id"),
            ("fetch_runs", "id"),
            ("author_monitors", "id"),
            ("author_monitor_papers", "author_monitor_id, paper_id"),
        ):
            if table in tables:
                selected[table] = jsonable_rows(
                    connection.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
                )
        foreign_keys = jsonable_rows(connection.execute("PRAGMA foreign_key_check").fetchall())
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        return {
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "foreign_key_check": foreign_keys,
            "integrity_check": integrity,
            "tables": selected,
        }
    finally:
        connection.close()


def normalized_state(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    volatile = {
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
        "searched_at",
        "started_at",
        "finished_at",
        "downloaded_at",
        "modified_at",
    }
    snapshot = snapshot or {}
    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        tables = {}
    result = {"user_version": int(snapshot.get("user_version") or 0), "tables": {}}
    for table, rows in tables.items():
        if not isinstance(rows, list):
            continue
        result["tables"][table] = [
            {key: value for key, value in row.items() if key not in volatile}
            for row in rows
            if isinstance(row, dict)
        ]
    return result


def database_orphans(storage: Storage) -> list[dict[str, Any]]:
    checks = {
        "resource_missing_paper": """
            SELECT resources.id AS id FROM resources
            LEFT JOIN papers ON papers.paper_id = resources.paper_id
            WHERE resources.paper_id IS NOT NULL AND papers.paper_id IS NULL
        """,
        "library_item_missing_paper": """
            SELECT library_items.id AS id FROM library_items
            LEFT JOIN papers ON papers.paper_id = library_items.paper_id
            WHERE papers.paper_id IS NULL
        """,
        "primary_missing_or_wrong_paper": """
            SELECT papers.paper_id AS id FROM papers
            LEFT JOIN resources ON resources.id = papers.primary_resource_id
            WHERE papers.primary_resource_id IS NOT NULL
              AND (resources.id IS NULL OR resources.paper_id != papers.paper_id)
        """,
        "preferred_missing_or_wrong_paper": """
            SELECT papers.paper_id AS id FROM papers
            LEFT JOIN resources ON resources.id = papers.preferred_resource_id
            WHERE papers.preferred_resource_id IS NOT NULL
              AND (resources.id IS NULL OR resources.paper_id != papers.paper_id)
        """,
        "supersedes_missing": """
            SELECT resources.id AS id FROM resources
            LEFT JOIN resources AS prior ON prior.id = resources.supersedes_resource_id
            WHERE resources.supersedes_resource_id IS NOT NULL AND prior.id IS NULL
        """,
    }
    found: list[dict[str, Any]] = []
    for kind, query in checks.items():
        for row in storage.conn.execute(query).fetchall():
            found.append({"kind": kind, "id": row["id"]})
    return found


def referenced_file_paths(storage: Storage) -> set[str]:
    values: set[str] = set()
    for row in storage.conn.execute(
        "SELECT main_pdf_path, merged_pdf_path, source_path FROM papers"
    ).fetchall():
        for value in row:
            if value:
                values.add(str(Path(str(value)).expanduser().resolve()))
    for row in storage.conn.execute("SELECT source_path, stored_path FROM resources").fetchall():
        for value in row:
            if value and Path(str(value)).expanduser().exists():
                values.add(str(Path(str(value)).expanduser().resolve()))
    return values


def orphan_owned_files(storage: Storage, profile: Profile) -> list[str]:
    from paper_monitor import finder_alias
    referenced = referenced_file_paths(storage)
    orphans: list[str] = []
    for root in (profile.library, profile.spaces, profile.publications, profile.associated, profile.pdfs):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if finder_alias.is_alias(path):
                target = finder_alias.resolve(path)
                # Uses real macOS Finder bookmarks as well as symlinks.
                # Exempt only a valid in-profile projection of registered bytes;
                # dangling, external, or unrelated aliases remain failures.
                owned = target.exists() and target.is_relative_to(profile.root.resolve())
                linked = str(target) in referenced or (target.is_dir() and any(
                    Path(value).is_relative_to(target) for value in referenced))
                if not owned or not linked:
                    orphans.append(str(path.absolute()))
                continue
            if not path.is_file():
                continue
            if str(path.resolve()) not in referenced:
                orphans.append(str(path.resolve()))
    return sorted(orphans)


def path_mapping_errors(storage: Storage, profile: Profile) -> list[str]:
    errors: list[str] = []
    allowed_roots = [
        profile.library.resolve(),
        profile.spaces.resolve(),
        profile.publications.resolve(),
        profile.associated.resolve(),
        profile.pdfs.resolve(),
        (profile.data / "library_imports").resolve(),
    ]
    for resource in storage.conn.execute("SELECT * FROM resources ORDER BY id").fetchall():
        for column in ("stored_path", "source_path"):
            value = resource[column]
            if not value:
                continue
            path = Path(str(value)).expanduser().resolve()
            if column == "stored_path" and not any(is_relative_to(path, root) for root in allowed_roots):
                errors.append(f"resource {resource['id']} stored_path outside fixture: {path}")
            if column == "stored_path" and not path.exists():
                errors.append(f"resource {resource['id']} missing stored_path: {path}")
    for paper in storage.conn.execute("SELECT * FROM papers ORDER BY paper_id").fetchall():
        primary_id = int(paper["primary_resource_id"] or 0)
        if not primary_id:
            continue
        primary = storage.get_paper_resource(primary_id)
        if not primary:
            errors.append(f"paper {paper['paper_id']} primary resource absent")
            continue
        canonical = str(paper["merged_pdf_path"] or paper["main_pdf_path"] or "")
        resource_path = Storage.resource_local_path(primary)
        if not canonical or Path(canonical).resolve() != Path(resource_path).resolve():
            errors.append(f"paper {paper['paper_id']} canonical/primary mismatch")
    return errors


def fixture_profile(parent: Profile, fixture_id: str) -> Profile:
    root = ensure_profile_path(parent.root / "state_fixtures" / fixture_id)
    root.mkdir(parents=True, exist_ok=False)
    child = Profile(run_id=parent.run_id, root=root)
    for directory in (
        child.library,
        child.spaces,
        child.publications,
        child.associated,
        child.pdfs,
        child.cache / "pdf_thumbs",
        child.cache / "web",
        child.config,
        child.logs,
        child.raw_network / "blobs",
        child.outputs,
        child.traces,
        child.reports,
        child.trash,
        child.root / "inputs",
    ):
        directory.mkdir(parents=True, exist_ok=False)
    shutil.copy2(parent.config / "journals.json", child.config / "journals.json")
    marker = {
        "format": "Gewu Insight Benchmark v2 isolated fixture profile",
        "format_version": 1,
        "run_id": parent.run_id,
        "root": str(child.root),
        "parent_profile": str(parent.root),
        "fixture_id": fixture_id,
        "created_at": utc_now(),
    }
    write_json_new(child.marker, marker)
    child.verify()
    return child


def make_pdf_bytes(label: str, *, pages: int = 1) -> bytes:
    temporary = Path(os.environ.get("TMPDIR", "/tmp")) / f"gewu-benchmark-{os.getpid()}-{hashlib.sha1(label.encode()).hexdigest()[:12]}.pdf"
    writer = PdfWriter()
    for _ in range(max(1, pages)):
        writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": label})
    with temporary.open("wb") as handle:
        writer.write(handle)
    payload = temporary.read_bytes()
    temporary.unlink()
    return payload


def clean_and_annotated_pdf_bytes(label: str, notes: int = 1) -> tuple[bytes, bytes]:
    base_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"gewu-clean-{os.getpid()}-{hashlib.sha1(label.encode()).hexdigest()[:12]}.pdf"
    annotated_path = base_path.with_name(base_path.stem + "-annotated.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": label})
    with base_path.open("wb") as handle:
        writer.write(handle)
    annotated = PdfWriter()
    annotated.append_pages_from_reader(PdfReader(str(base_path)))
    for index in range(max(1, notes)):
        annotated.add_annotation(
            page_number=0,
            annotation=Text(
                rect=(72 + index * 8, 700 - index * 12, 96 + index * 8, 724 - index * 12),
                text=f"benchmark note {index + 1}",
            ),
        )
    with annotated_path.open("wb") as handle:
        annotated.write(handle)
    clean_bytes = base_path.read_bytes()
    annotated_bytes = annotated_path.read_bytes()
    base_path.unlink()
    annotated_path.unlink()
    return clean_bytes, annotated_bytes


@dataclass
class Harness:
    parent: Profile
    profile: Profile
    family: dict[str, Any]
    variant: int
    structural_variant: str
    code_path_tags: list[str]
    api: ApiServer
    storage: Storage
    trace: HashChainJsonl
    paper_ids: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    operations: int = 0
    observed_steps: list[str] = field(default_factory=list)

    def observe(self, step: str, action_result: Any = None) -> dict[str, Any]:
        api_payloads: dict[str, Any] = {
            "health": self.api.get_json("/api/health"),
        }
        ui_payloads: dict[str, Any] = {
            "root_html_sha256": sha256_bytes(self.api.get_text("/").encode("utf-8")),
            "library_bootstrap": self.api.get_json("/api/library/bootstrap"),
            "library_navigation": self.api.get_json("/api/library"),
            "my_publications": self.api.get_json("/api/my-publications"),
        }
        for paper_id in sorted(set(self.paper_ids)):
            try:
                api_payloads[paper_id] = {
                    "paper": self.api.get_json("/api/paper", {"paper_id": paper_id}),
                    "files": self.api.get_json("/api/paper-files", {"paper_id": paper_id}),
                }
                ui_payloads.setdefault("paper_locations", {})[paper_id] = self.api.get_json(
                    "/api/library/paper-locations", {"paper_id": paper_id}
                )
            except Exception as exc:
                api_payloads[paper_id] = {"error": f"{type(exc).__name__}: {exc}"}
                ui_payloads.setdefault("paper_locations", {})[paper_id] = {
                    "error": f"{type(exc).__name__}: {exc}"
                }
        snapshot = sqlite_snapshot(self.profile.db)
        filesystem = filesystem_inventory(
            [self.profile.library, self.profile.spaces, self.profile.publications, self.profile.associated, self.profile.pdfs, self.profile.trash]
        )
        event = self.trace.append(
            {
                "event_type": "state_transition_observation",
                "run_id": self.parent.run_id,
                "fixture_id": self.profile.root.name,
                "family_id": self.family["id"],
                "variant": self.variant,
                "structural_variant": self.structural_variant,
                "code_path_tags": self.code_path_tags,
                "step": step,
                "action_result": action_result,
                "ui": ui_payloads,
                "api": api_payloads,
                "sqlite": snapshot,
                "filesystem": filesystem,
            }
        )
        self.operations += 1
        self.observed_steps.append(step)
        return event

    def act(self, name: str, action: Callable[[], Any]) -> Any:
        try:
            result = action()
        except Exception as exc:
            self.observe(
                name,
                {
                    "status": "expected_or_unexpected_exception",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            raise
        serializable = result
        try:
            json.dumps(serializable)
        except (TypeError, ValueError):
            serializable = repr(result)
        self.observe(name, {"status": "completed", "result": serializable})
        return result

    def expected_exception(self, name: str, action: Callable[[], Any], pattern: str = "") -> str:
        try:
            action()
        except Exception as exc:
            message = str(exc)
            matched = not pattern or re.search(pattern, message, flags=re.IGNORECASE) is not None
            self.observe(
                name,
                {
                    "status": "expected_exception" if matched else "wrong_exception",
                    "type": type(exc).__name__,
                    "message": message,
                    "pattern": pattern,
                    "matched": matched,
                },
            )
            if not matched:
                raise AssertionError(f"Exception did not match {pattern!r}: {message}") from exc
            return message
        self.observe(name, {"status": "missing_expected_exception", "pattern": pattern})
        raise AssertionError(f"Expected exception was not raised: {name}")

    def audit_product_rejection(
        self,
        name: str,
        action: Callable[[], Any],
        pattern: str = "",
    ) -> dict[str, Any]:
        """Record a product rejection decision without turning acceptance into a runner crash."""

        try:
            result = action()
        except Exception as exc:
            message = str(exc)
            matched = not pattern or re.search(pattern, message, flags=re.IGNORECASE) is not None
            outcome = {
                "status": "product_rejected" if matched else "product_rejected_unexpected_reason",
                "rejected": True,
                "reason_matched": matched,
                "type": type(exc).__name__,
                "message": message,
                "pattern": pattern,
            }
            self.observe(name, outcome)
            return outcome
        serializable = result
        try:
            json.dumps(serializable)
        except (TypeError, ValueError):
            serializable = repr(result)
        outcome = {
            "status": "product_accepted_invalid_input",
            "rejected": False,
            "reason_matched": False,
            "pattern": pattern,
            "result": serializable,
        }
        self.observe(name, outcome)
        return outcome

    def add_work(self, suffix: str, *, source: str = "fixture", doi: str | None = None, title: str | None = None) -> str:
        doi = doi or f"10.9999/{self.family['id'].lower()}.{self.variant}.{suffix}"
        title = title or f"V4 synthetic {self.family['id']} {self.variant} {suffix}"
        paper_id = make_paper_id(doi, title, "Benchmark Journal", "2026-09-25")
        self.storage.upsert_paper(
            {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
                "journal": "Benchmark Journal",
                "publication_date": "2026-09-25",
                "source": source,
                "type": "article",
                "section_allowed": True,
                "raw": {"benchmark_fixture": self.profile.root.name, "variant": self.variant},
            }
        )
        if paper_id not in self.paper_ids:
            self.paper_ids.append(paper_id)
        return paper_id

    def add_library_work(self, suffix: str = "work", *, title: str | None = None) -> tuple[str, dict[str, Any]]:
        paper_id = self.add_work(suffix, title=title)
        item = self.storage.add_library_item(paper_id=paper_id, folder_id=1)
        return paper_id, item

    def attach_pdf(
        self,
        paper_id: str,
        filename: str,
        payload: bytes,
        *,
        version_role: str,
        file_role: str = "publication_version",
        version_label: str = "",
    ) -> dict[str, Any]:
        return ui_server.attach_file_to_paper(
            self.storage,
            paper_id=paper_id,
            filename=filename,
            content=payload,
            file_role=file_role,
            version_role=version_role,
            version_label=version_label,
            added_via="benchmark_v4_retained_requirement",
        )


def check(value: bool, evidence: Any) -> dict[str, Any]:
    return {"status": "pass" if value else "fail", "evidence": evidence}


def resource_by_role(storage: Storage, paper_id: str, version_role: str) -> list[dict[str, Any]]:
    return [
        resource
        for resource in storage.list_paper_resources(paper_id)
        if str(resource.get("version_role") or "") == version_role
    ]


def paper_provenance_snapshot(storage: Storage, paper_id: str) -> dict[str, Any]:
    """Audit normalized provenance plus its legacy paper-row projection.

    Task C keeps the historical fixture denominator and invariant name.  This
    helper strengthens the evidence behind C01's association-multiplicity
    invariant for schema 13 without turning a normalized-table implementation
    detail into a new benchmark fixture.
    """
    expected_monitors = {"journal", "subject", "author"}
    table_exists = bool(
        storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_source_observations'"
        ).fetchone()
    )
    rows: list[dict[str, Any]] = []
    if table_exists:
        rows = [
            dict(row)
            for row in storage.conn.execute(
                """
                SELECT id, paper_id, source_kind, source_name, source_key,
                       first_seen_at, last_seen_at
                FROM paper_source_observations
                WHERE paper_id = ?
                ORDER BY source_kind, source_name, source_key, id
                """,
                (paper_id,),
            ).fetchall()
        ]
    identities = [
        (
            str(row.get("source_kind") or "").casefold(),
            str(row.get("source_name") or "").casefold(),
            str(row.get("source_key") or "").casefold(),
        )
        for row in rows
    ]
    monitor_names = {
        identity[1]
        for identity in identities
        if identity[0] == "monitor"
    }
    paper = storage.get_paper(paper_id) or {}
    try:
        raw = json.loads(str(paper.get("raw_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw_sources = {
        str(item).casefold()
        for item in raw.get("_paper_monitor_sources") or []
        if isinstance(item, str) and item.strip()
    }
    source_count = int(paper.get("source_count") or 0)
    return {
        "table_exists": table_exists,
        "rows": rows,
        "observation_count": len(rows),
        "observation_rows_unique": len(identities) == len(set(identities)),
        "monitor_names": sorted(monitor_names),
        "expected_monitor_names": sorted(expected_monitors),
        "expected_monitors_present": expected_monitors.issubset(monitor_names),
        "raw_projection_sources": sorted(raw_sources),
        "raw_projection_complete": expected_monitors.issubset(raw_sources),
        "source_count": source_count,
        "source_count_consistent": source_count >= len(rows) and source_count >= 3,
    }


def scenario_c01(h: Harness) -> dict[str, Any]:
    doi = f"10.9999/three-entry.{h.variant}"
    title = f"Schema 10 C01 shared work {h.variant}"
    arxiv_id = f"2608.{10000 + h.variant:05d}"

    def axis_payload(
        axis: str,
        paper_id: str,
        observed_doi: str = "",
        *,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "paper_id": paper_id,
            "doi": observed_doi,
            "title": title,
            "journal": "Benchmark Journal",
            "publication_date": "2026-09-25",
            "source": axis,
            "type": "article",
            "section_allowed": True,
            "raw": raw or {"axis": axis, "variant": h.variant},
        }

    def merge_axis(
        axis: str,
        paper_id: str,
        observed_doi: str = "",
        *,
        raw: dict[str, Any] | None = None,
        replace_metadata: bool = False,
    ) -> None:
        payload = axis_payload(axis, paper_id, observed_doi, raw=raw)
        existing = h.storage.get_paper(paper_id)
        if replace_metadata and existing:
            h.storage.refresh_paper_metadata(
                paper_id,
                ui_server.merge_refreshed_metadata(existing, payload),
            )
        elif existing:
            h.storage.merge_paper_missing_metadata(payload, source_name=axis)
        else:
            h.storage.upsert_paper(payload)
        if paper_id not in h.paper_ids:
            h.paper_ids.append(paper_id)

    def journal_axis(
        paper_id: str,
        observed_doi: str = doi,
        *,
        raw: dict[str, Any] | None = None,
        replace_metadata: bool = False,
    ) -> None:
        merge_axis(
            "journal",
            paper_id,
            observed_doi,
            raw=raw,
            replace_metadata=replace_metadata,
        )
        fetch_run_id = h.storage.start_fetch_run(
            monitor_type="journal",
            source="benchmark_journal",
            journal="Benchmark Journal",
            window_start="2026-09-25",
            window_end="2026-09-25",
            started_at=utc_now(),
        )
        h.storage.record_journal_monitor_paper(
            fetch_run_id=fetch_run_id,
            paper_id=paper_id,
            source="benchmark_journal",
        )
        h.storage.finish_fetch_run(
            fetch_run_id,
            status="success",
            records_found=1,
            message="isolated fixture",
        )
        h.observe("journal_ingestion")

    def subject_axis(
        paper_id: str,
        observed_doi: str = doi,
        *,
        raw: dict[str, Any] | None = None,
    ) -> None:
        merge_axis("subject", paper_id, observed_doi, raw=raw)
        h.storage.record_theme_result(
            paper_id=paper_id,
            group_key=f"SUBJ{h.variant + 1:02d}",
            group_name="Blinded subject",
            query="frozen query",
            score=2,
            hits=["fixture"],
            window_start="2026-09-25",
            window_end="2026-09-25",
        )
        h.observe("subject_ingestion")

    def author_axis(paper_id: str, observed_doi: str = "") -> None:
        author = h.storage.add_author_monitor(
            {
                "source_type": "google_scholar",
                "source_author_id": f"BENCHAUTHOR{h.variant:02d}",
                "user_id": f"BENCHAUTHOR{h.variant:02d}",
                "name": f"Benchmark Author {h.variant}",
                "url": f"https://scholar.google.com/citations?user=BENCHAUTHOR{h.variant:02d}",
            }
        )
        merge_axis(
            "author",
            paper_id,
            observed_doi,
            raw={"axis": "author", "scholar_key": f"case-{h.variant}"},
        )
        h.storage.add_author_monitor_paper(
            author_monitor_id=int(author["id"]), paper_id=paper_id, scholar_key=f"case-{h.variant}"
        )
        h.observe("author_ingestion")

    def resolve_author(candidate: dict[str, Any]) -> str:
        candidate_paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
        match = ui_server.existing_paper_for_author_monitor(h.storage, candidate_paper)
        if match:
            return str(match["paper_id"])
        normalized = ui_server.paper_from_publication_candidate(candidate)
        return str(normalized["paper_id"])

    canonical = ui_server.paper_from_publication_candidate(
        {
            "paper": {
                "doi": doi,
                "title": title,
                "journal": "Benchmark Journal",
                "publication_date": "2026-09-25",
                "source": "journal",
            }
        }
    )
    if h.variant == 0:
        paper_id = str(canonical["paper_id"])
        journal_axis(paper_id, doi)
        subject_candidate = {
            "paper": {
                "paper_id": f"unseen-subject-doi-{h.variant}",
                "doi": doi.upper(),
                "title": title,
                "publication_date": "2026-09-25",
            }
        }
        subject_id = resolve_author(subject_candidate)
        subject_axis(subject_id, doi.upper())
        author_candidate = {
            "paper": {
                "paper_id": f"unseen-author-doi-{h.variant}",
                "doi": doi,
                "title": title,
                "publication_date": "2026-09-25",
            }
        }
        paper_id = resolve_author(author_candidate)
        author_axis(paper_id, doi)
    elif h.variant == 1:
        arxiv_candidate = ui_server.paper_from_publication_candidate(
            {
                "paper": {
                    "title": title,
                    "journal": "arXiv",
                    "publication_date": "2026-09-25",
                    "source": "arxiv",
                },
                "raw": {"arxiv_id": arxiv_id, "versioned_arxiv_id": f"{arxiv_id}v1"},
            }
        )
        paper_id = str(arxiv_candidate["paper_id"])
        subject_axis(
            paper_id,
            "",
            raw={"arxiv_id": arxiv_id, "versioned_arxiv_id": f"{arxiv_id}v1", "axis": "subject"},
        )
        inventory_record = {
            "doi": doi.lower(),
            "arxiv_id": arxiv_id,
            "source_path": "",
            "size_bytes": None,
        }
        matched_id = existing_paper_id(
            inventory_record,
            build_existing_index(h.storage),
            ["doi", "arxiv_id"],
        )
        journal_id = matched_id or str(canonical["paper_id"])
        journal_axis(
            journal_id,
            doi,
            raw={"arxiv_id": arxiv_id, "versioned_arxiv_id": f"{arxiv_id}v3", "axis": "journal"},
            replace_metadata=bool(matched_id),
        )
        paper_id = resolve_author(
            {"paper": {"paper_id": f"unseen-author-{h.variant}", "doi": doi, "title": title, "publication_date": "2026-09-25"}}
        )
        author_axis(paper_id, doi)
    elif h.variant == 2:
        scholar_candidate = ui_server.paper_from_publication_candidate(
            {
                "paper": {
                    "title": title,
                    "journal": "Benchmark Journal",
                    "publication_date": "2026-09-25",
                    "source": "google_scholar",
                }
            }
        )
        paper_id = str(scholar_candidate["paper_id"])
        author_axis(paper_id, "")
        journal_candidate = {
            "paper": {
                "paper_id": str(canonical["paper_id"]),
                "doi": doi,
                "title": title,
                "journal": "Benchmark Journal",
                "publication_date": "2026-09-25",
            }
        }
        journal_id = resolve_author(journal_candidate)
        journal_axis(journal_id, doi, replace_metadata=h.storage.get_paper(journal_id) is not None)
        paper_id = resolve_author(
            {
                "paper": {
                    "paper_id": f"unseen-subject-{h.variant}",
                    "doi": doi,
                    "title": title,
                    "publication_date": "2026-09-25",
                }
            }
        )
        subject_axis(paper_id, doi)
    else:
        paper_id = str(canonical["paper_id"])
        journal_axis(paper_id, doi)
        author_id = resolve_author(
            {
                "paper": {
                    "paper_id": f"unseen-scholar-only-{h.variant}",
                    "doi": "",
                    "title": title,
                    "journal": "",
                    "publication_date": "2026",
                }
            }
        )
        author_axis(author_id, "")
        paper_id = resolve_author(
            {
                "paper": {
                    "paper_id": f"unseen-subject-{h.variant}",
                    "doi": doi,
                    "title": title,
                    "publication_date": "2026-09-25",
                }
            }
        )
        subject_axis(paper_id, doi)
    normalized_title = ui_server.normalize_publication_title(title)
    identity_rows = h.storage.conn.execute(
        "SELECT paper_id, doi, title, raw_json FROM papers WHERE lower(title)=lower(?) ORDER BY paper_id",
        (normalized_title,),
    ).fetchall()
    identity_count = len(identity_rows)
    doi_count = int(
        h.storage.conn.execute("SELECT COUNT(*) FROM papers WHERE lower(doi)=lower(?)", (doi,)).fetchone()[0]
    )
    associations = {
        "theme": int(h.storage.conn.execute("SELECT COUNT(*) FROM theme_results WHERE paper_id=?", (paper_id,)).fetchone()[0]),
        "author": int(h.storage.conn.execute("SELECT COUNT(*) FROM author_monitor_papers WHERE paper_id=?", (paper_id,)).fetchone()[0]),
        "journal": int(h.storage.conn.execute("SELECT COUNT(*) FROM journal_monitor_papers WHERE paper_id=?", (paper_id,)).fetchone()[0]),
        "journal_run": int(h.storage.conn.execute("SELECT COUNT(*) FROM fetch_runs WHERE monitor_type='journal'").fetchone()[0]),
        "source_count": int((h.storage.get_paper(paper_id) or {}).get("source_count") or 0),
    }
    provenance = paper_provenance_snapshot(h.storage, paper_id)
    return {
        "identity_uniqueness": check(
            identity_count == 1 and doi_count == 1,
            {"doi": doi, "doi_rows": doi_count, "same_title_rows": [dict(row) for row in identity_rows]},
        ),
        "association_multiplicity": check(
            associations["theme"] == 1
            and associations["author"] == 1
            and associations["journal"] == 1
            and associations["journal_run"] == 1
            and associations["source_count"] >= 3
            and provenance["table_exists"]
            and provenance["observation_rows_unique"]
            and provenance["expected_monitors_present"]
            and provenance["raw_projection_complete"]
            and provenance["source_count_consistent"],
            {"associations": associations, "provenance": provenance},
        ),
    }


def simulate_download_replacement(
    h: Harness,
    paper_id: str,
    payload: bytes,
    filename: str,
    source_url: str,
) -> dict[str, Any]:
    snapshot = ui_server.snapshot_primary_resource_before_download(h.storage, paper_id, force=True)
    # A successful product download exposes a final managed PDF path, not the
    # transient fixture input area used for manual attachment payloads.
    temporary = h.profile.pdfs / filename
    temporary.write_bytes(payload)
    h.storage.update_download_status(
        paper_id,
        status="success",
        message="benchmark simulated successful product download",
        main_pdf_path=str(temporary),
        merged_pdf_path=str(temporary),
        pdf_url=source_url,
    )
    current = ui_server.register_downloaded_paper_resource(
        h.storage,
        paper_id,
        result={"status": "success", "main_pdf_url": source_url},
        snapshot=snapshot,
    )
    ui_server.cleanup_download_resource_snapshot(snapshot)
    return current or {}


def scenario_c02(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("preprint-vor")
    if h.variant == 3:
        # This branch really exercises reverse arrival order: no preprint
        # exists when the version of record is registered.
        vor = simulate_download_replacement(
            h,
            paper_id,
            make_pdf_bytes("c02-vor-first"),
            "published-first.pdf",
            "https://publisher.example/vor/c02-3",
        )
        h.observe("version_of_record_first")
        preprint = h.attach_pdf(
            paper_id,
            "late-preprint.pdf",
            make_pdf_bytes("c02-late-preprint"),
            version_role="preprint",
            version_label="Preprint v1",
        )
        h.observe("late_preprint_history")
    else:
        preprint = h.attach_pdf(
            paper_id,
            f"preprint-v{1 + h.variant}.pdf",
            make_pdf_bytes(f"c02-preprint-{h.variant}"),
            version_role="preprint",
            version_label=f"Preprint v{1 + h.variant}",
        )
        h.observe("preprint_available")
    if h.variant == 1:
        later = h.attach_pdf(
            paper_id,
            "preprint-v3.pdf",
            make_pdf_bytes("c02-preprint-v3"),
            version_role="preprint",
            version_label="Preprint v3",
        )
        preprint = later
        h.observe("later_preprint_revision")
    if h.variant == 2:
        h.storage.refresh_paper_metadata(
            paper_id,
            {
                "paper_id": paper_id,
                "doi": (h.storage.get_paper(paper_id) or {}).get("doi"),
                "title": "Publisher title changed after preprint",
                "journal": "Benchmark Journal",
                "publication_date": "2026-09-25",
                "source": "publisher",
                "raw": {"title_change": True},
            },
        )
        h.observe("publisher_metadata_refresh")
    if h.variant != 3:
        vor = simulate_download_replacement(
            h,
            paper_id,
            make_pdf_bytes(f"c02-vor-{h.variant}"),
            "published.pdf",
            f"https://publisher.example/vor/c02-{h.variant}",
        )
        h.observe("version_of_record_download")
    resources = h.storage.list_paper_resources(paper_id)
    current = h.storage.resolve_primary_paper_resource(paper_id) or {}
    prior_ids = {int(item["id"]) for item in resources if item.get("file_type") == "preprint"}
    lineage_ok = (
        int(vor.get("supersedes_resource_id") or 0) == 0
        if h.variant == 3
        else int(vor.get("supersedes_resource_id") or 0) in prior_ids
    )
    previous_paths = [Storage.resource_local_path(item) for item in resources if int(item["id"]) in prior_ids]
    preserved = bool(previous_paths) and all(Path(path).exists() for path in previous_paths)
    return {
        "resource_set_integrity": check(len(resources) >= 2 and preserved, {"count": len(resources), "previous_paths": previous_paths}),
        "resource_role_correctness": check(
            any(item.get("file_type") == "preprint" for item in resources)
            and any(item.get("file_type") == "published_version" for item in resources),
            [(item["id"], item.get("file_type")) for item in resources],
        ),
        "lineage_integrity": check(lineage_ok, {"vor": vor.get("id"), "supersedes": vor.get("supersedes_resource_id"), "prior_ids": sorted(prior_ids)}),
        "current_selection": check(current.get("file_type") == "published_version", current),
        "path_mapping": check(not path_mapping_errors(h.storage, h.profile), path_mapping_errors(h.storage, h.profile)),
        "no_unexpected_deletion": check(preserved, previous_paths),
    }


def scenario_c03(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("accepted-published")
    accepted: dict[str, Any]
    duplicate_reuse_ok = True
    if h.variant == 3:
        vor = simulate_download_replacement(
            h,
            paper_id,
            make_pdf_bytes("c03-vor-first"),
            "publisher-version-first.pdf",
            "https://publisher.example/vor/c03-3",
        )
        h.observe("published_version")
        accepted = h.attach_pdf(
            paper_id,
            "late-accepted-manuscript.pdf",
            make_pdf_bytes("c03-late-accepted"),
            version_role="accepted_manuscript",
            version_label="Accepted Manuscript",
        )
        h.observe("late_accepted_manuscript")
    else:
        if h.variant == 1:
            h.attach_pdf(
                paper_id,
                "submitted-preprint.pdf",
                make_pdf_bytes("c03-preprint"),
                version_role="preprint",
                version_label="Preprint",
            )
            h.observe("preprint_before_acceptance")
        accepted_payload = make_pdf_bytes(f"c03-accepted-{h.variant}")
        accepted = h.attach_pdf(
            paper_id,
            "accepted-manuscript.pdf",
            accepted_payload,
            version_role="accepted_manuscript",
            version_label="Accepted Manuscript",
        )
        h.observe("accepted_manuscript")
        if h.variant == 2:
            duplicate = h.attach_pdf(
                paper_id,
                "repository-accepted-copy.pdf",
                accepted_payload,
                version_role="accepted_manuscript",
                version_label="Accepted Manuscript",
            )
            duplicate_reuse_ok = int(duplicate["id"]) == int(accepted["id"])
            h.state["accepted_duplicate_reused"] = duplicate_reuse_ok
            h.observe("duplicate_accepted_source")
        vor = simulate_download_replacement(
            h,
            paper_id,
            make_pdf_bytes(f"c03-vor-{h.variant}"),
            "publisher-version.pdf",
            f"https://publisher.example/vor/c03-{h.variant}",
        )
        h.observe("published_version")
    resources = h.storage.list_paper_resources(paper_id)
    current = h.storage.resolve_primary_paper_resource(paper_id) or {}
    accepted_rows = [item for item in resources if item.get("file_type") == "accepted_manuscript"]
    published_rows = [item for item in resources if item.get("file_type") == "published_version"]
    preserved = all(Path(Storage.resource_local_path(item)).exists() for item in accepted_rows)
    lineage_ok = (
        int(vor.get("supersedes_resource_id") or 0) == 0
        if h.variant == 3
        else int(vor.get("supersedes_resource_id") or 0) == int(accepted.get("id") or 0)
    )
    return {
        "resource_set_integrity": check(
            bool(accepted_rows and published_rows and preserved and duplicate_reuse_ok),
            {
                "accepted": accepted_rows,
                "published": published_rows,
                "accepted_duplicate_reused": duplicate_reuse_ok,
            },
        ),
        "resource_role_correctness": check(bool(accepted_rows and published_rows), [(item["id"], item.get("file_type")) for item in resources]),
        "lineage_integrity": check(lineage_ok, {"vor_supersedes": vor.get("supersedes_resource_id"), "accepted_id": accepted.get("id")}),
        "current_selection": check(current.get("file_type") == "published_version", current),
        "no_unexpected_deletion": check(preserved, [Storage.resource_local_path(item) for item in accepted_rows]),
    }


def scenario_c04(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("identical")
    payload = make_pdf_bytes(f"c04-identical-{h.variant}", pages=1 + (h.variant % 2))
    first = h.attach_pdf(
        paper_id,
        f"initial-{h.variant}.pdf",
        payload,
        version_role="preprint" if h.variant == 3 else "version_of_record",
    )
    h.observe("initial_file")
    before = h.storage.list_paper_resources(paper_id)
    duplicate_flags: list[bool] = []
    if h.variant in {0, 1}:
        second_name = f"initial-{h.variant}.pdf" if h.variant == 0 else "renamed-source.pdf"
        third_name = f"initial-{h.variant}.pdf" if h.variant == 0 else "third-renamed-source.pdf"
        second = h.attach_pdf(
            paper_id,
            second_name,
            payload,
            version_role=str(first.get("version_role") or "other"),
        )
        h.observe("byte_identical_manual_refresh")
        third = h.attach_pdf(
            paper_id,
            third_name,
            payload,
            version_role=str(first.get("version_role") or "other"),
        )
        h.observe("idempotent_manual_rerun")
        duplicate_flags = [bool(second.get("duplicate")), bool(third.get("duplicate"))]
    elif h.variant == 2:
        second = simulate_download_replacement(
            h,
            paper_id,
            payload,
            "forced-refresh.pdf",
            "https://publisher.example/c04/forced-refresh",
        )
        h.observe("byte_identical_forced_download_refresh")
        third = simulate_download_replacement(
            h,
            paper_id,
            payload,
            "forced-refresh-repeat.pdf",
            "https://publisher.example/c04/forced-refresh-repeat",
        )
        h.observe("idempotent_forced_download_rerun")
    else:
        source_one = h.profile.root / "inputs" / "publisher-copy-one.pdf"
        source_one.write_bytes(payload)
        ui_server.attach_downloaded_publisher_pdf_to_paper(
            h.storage,
            paper_id=paper_id,
            context={"publisher_download_target_url": "https://publisher.example/c04/repair-one"},
            source_path=source_one,
        )
        second = h.storage.get_paper_resource(int(first["id"])) or {}
        h.observe("publisher_duplicate_role_repair")
        source_two = h.profile.root / "inputs" / "publisher-copy-two.pdf"
        source_two.write_bytes(payload)
        ui_server.attach_downloaded_publisher_pdf_to_paper(
            h.storage,
            paper_id=paper_id,
            context={"publisher_download_target_url": "https://publisher.example/c04/repair-two"},
            source_path=source_two,
        )
        third = h.storage.get_paper_resource(int(first["id"])) or {}
        h.observe("publisher_duplicate_role_repair_rerun")
    after = h.storage.list_paper_resources(paper_id)
    reused = int(first["id"]) == int(second["id"]) == int(third["id"])
    return {
        "resource_set_integrity": check(len(before) == len(after) == 1, {"before": len(before), "after": len(after)}),
        "current_selection": check(int((h.storage.resolve_primary_paper_resource(paper_id) or {}).get("id") or 0) == int(first["id"]), first),
        "exact_idempotence": check(
            reused,
            {
                "ids": [first["id"], second["id"], third["id"]],
                "manual_duplicate_flags": duplicate_flags,
                "final_role": third.get("version_role"),
            },
        ),
        "no_orphan_owned_files": check(not orphan_owned_files(h.storage, h.profile), orphan_owned_files(h.storage, h.profile)),
    }


def scenario_c05(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("clean-annotated")
    clean, annotated = clean_and_annotated_pdf_bytes(f"c05-{h.variant}", notes=1 + h.variant)
    ordered = [("clean.pdf", clean), ("annotated.pdf", annotated)]
    if h.variant in {1, 3}:
        ordered.reverse()
    added: list[dict[str, Any]] = []
    for filename, payload in ordered:
        added.append(
            h.attach_pdf(
                paper_id,
                filename,
                payload,
                version_role="preprint",
                version_label="Annotated copy" if "annotated" in filename else "Clean copy",
            )
        )
        h.observe(f"attach_{Path(filename).stem}")
    if h.variant == 2:
        refreshed = ui_server.refresh_paper_resource_fingerprints(h.storage, paper_id)
        h.observe("explicit_fingerprint_refresh", refreshed)
    elif h.variant == 3:
        annotated_resource = next(
            resource for resource in h.storage.list_paper_resources(paper_id)
            if str(resource.get("original_filename") or "") == "annotated.pdf"
        )
        repaired = ui_server.update_paper_resource_role(
            h.storage,
            paper_id,
            int(annotated_resource["id"]),
            "publication_version",
            "preprint",
            is_annotated=True,
        )
        h.observe("manual_annotation_role_repair", repaired)
    resources = h.storage.list_paper_resources(paper_id)
    exact = {str(item.get("sha256") or "") for item in resources}
    content = {str(item.get("content_sha256") or "") for item in resources}
    annotated_rows = [item for item in resources if item.get("annotation_state") == "annotated"]
    unannotated_rows = [item for item in resources if item.get("annotation_state") == "unannotated"]
    paths_exist = all(Path(Storage.resource_local_path(item)).exists() for item in resources)
    relation_populated = (
        len(content) == 1 and "" not in content
        and len(annotated_rows) == 1 and len(unannotated_rows) == 1
    )
    noncollapse = len(resources) == 2 and len(exact) == 2 and "" not in exact
    return {
        "resource_set_integrity": check(len(resources) == 2 and paths_exist, resources),
        "content_relation_populated": check(
            relation_populated,
            {
                "content_sha256": sorted(content),
                "annotated_resources": len(annotated_rows),
                "unannotated_resources": len(unannotated_rows),
            },
        ),
        "content_noncollapse": check(
            noncollapse,
            {"resource_count": len(resources), "exact_sha256": sorted(exact)},
        ),
        "current_selection": check(int((h.storage.resolve_primary_paper_resource(paper_id) or {}).get("id") or 0) in {int(item["id"]) for item in resources}, h.storage.resolve_primary_paper_resource(paper_id)),
        "no_unexpected_deletion": check(paths_exist, [Storage.resource_local_path(item) for item in resources]),
    }


def scenario_c06(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("attachments")
    primary = h.attach_pdf(
        paper_id,
        "published.pdf",
        make_pdf_bytes(f"c06-primary-{h.variant}"),
        version_role="version_of_record",
    )
    h.observe("primary_publication")
    supplement = h.attach_pdf(
        paper_id,
        f"supplement-{h.variant}.pdf",
        make_pdf_bytes(f"c06-supplement-{h.variant}"),
        file_role="supplement" if h.variant != 1 else "other",
        version_role="",
    )
    h.observe("related_pdf")
    note = ui_server.attach_file_to_paper(
        h.storage,
        paper_id=paper_id,
        filename=f"notes-{h.variant}.md",
        content=b"# benchmark note\n",
        file_role="note",
        added_via="benchmark_v4_retained_requirement",
    )
    h.observe("non_pdf_attachment")
    before = h.storage.get_paper(paper_id) or {}
    manual_selected: dict[str, Any] = {}
    manual_flag = False
    if h.variant < 3:
        preferred_target = note if h.variant == 2 else supplement
        preference_outcome = h.api.post_json(
            "/api/paper-files/preferred",
            {"paper_id": paper_id, "resource_id": int(preferred_target["id"])},
        )
        manual_selected = h.storage.resolve_default_paper_resource(paper_id) or {}
        manual_flag = bool(int((h.storage.get_paper(paper_id) or {}).get("preferred_resource_manual") or 0))
        h.observe("manual_preferred_secondary", preference_outcome)
        h.storage.set_preferred_paper_resource(paper_id, None)
        h.observe("clear_manual_preference")
    else:
        preference_outcome = {
            "status": "not_attempted_automatic_selection_control",
            "accepted": False,
            "target_resource_id": None,
        }
        h.observe("automatic_selection_control", preference_outcome)
    current = h.storage.resolve_default_paper_resource(paper_id) or {}
    paper = h.storage.get_paper(paper_id) or {}
    resources = h.storage.list_paper_resources(paper_id)
    role_ok = (
        any(item.get("file_type") in {"supplementary_material", "other"} for item in resources)
        and any(item.get("file_type") == "other" and item.get("kind") != "pdf" for item in resources)
    )
    preference_safe = (
        h.variant == 3
        or (
            int(manual_selected.get("id") or 0) == int(preferred_target["id"])
            and manual_flag
            and int(paper.get("preferred_resource_id") or 0) == 0
            and not bool(int(paper.get("preferred_resource_manual") or 0))
        )
    )
    return {
        "resource_set_integrity": check(len(resources) == 3, resources),
        "resource_role_correctness": check(role_ok, [(item["id"], item.get("file_type")) for item in resources]),
        "current_selection": check(int(current.get("id") or 0) == int(primary["id"]), {"current": current, "primary": primary["id"]}),
        "preferred_selection": check(
            preference_safe and int(paper.get("preferred_resource_id") or 0) == 0,
            {
                "product_outcome": preference_outcome,
                "manual_selected": manual_selected,
                "manual_flag": manual_flag,
                "preferred": paper.get("preferred_resource_id"),
                "before": before.get("preferred_resource_id"),
            },
        ),
    }


def scenario_c07(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("preference")
    published = h.attach_pdf(
        paper_id,
        "published.pdf",
        make_pdf_bytes(f"c07-vor-{h.variant}"),
        version_role="version_of_record",
    )
    preprint = h.attach_pdf(
        paper_id,
        f"preprint-v{h.variant + 1}.pdf",
        make_pdf_bytes(f"c07-preprint-{h.variant}"),
        version_role="preprint",
        version_label=f"Preprint v{h.variant + 1}",
    )
    accepted: dict[str, Any] | None = None
    if h.variant == 1:
        accepted = h.attach_pdf(
            paper_id,
            "accepted-manuscript.pdf",
            make_pdf_bytes("c07-accepted"),
            version_role="accepted_manuscript",
            version_label="Accepted Manuscript",
        )
    h.observe("automatic_ranking")
    automatic = h.storage.resolve_default_paper_resource(paper_id) or {}
    preferred_target = preprint
    if h.variant == 1 and accepted:
        preferred_target = accepted
    elif h.variant == 2:
        preferred_target = published
    ui_server.promote_paper_resource(
        h.storage, paper_id, int(preferred_target["id"]), manual_preferred=True
    )
    h.observe("manual_preference", {"target_resource_id": preferred_target["id"]})
    manual = h.storage.resolve_default_paper_resource(paper_id) or {}
    preferred_before_clear = h.storage.get_paper(paper_id) or {}
    preferred_id = int(preferred_before_clear.get("preferred_resource_id") or 0)
    preferred_manual = bool(int(preferred_before_clear.get("preferred_resource_manual") or 0))
    lock_held_after_new_arrival = True
    newest_published: dict[str, Any] | None = None
    if h.variant == 3:
        newest_published = h.attach_pdf(
            paper_id,
            "newer-published.pdf",
            make_pdf_bytes("c07-newer-vor"),
            version_role="version_of_record",
            version_label="Published Version",
        )
        while_locked = h.storage.resolve_default_paper_resource(paper_id) or {}
        lock_held_after_new_arrival = int(while_locked.get("id") or 0) == int(preprint["id"])
        h.observe(
            "new_vor_arrived_under_manual_preference",
            {"resolved": while_locked.get("id"), "new_resource": newest_published.get("id")},
        )
    h.storage.set_preferred_paper_resource(paper_id, None)
    resolved = h.storage.resolve_default_paper_resource(paper_id)
    h.observe("clear_manual_preference")
    restored = h.storage.resolve_primary_paper_resource(paper_id) or {}
    paper = h.storage.get_paper(paper_id) or {}
    expected_count = 3 if h.variant in {1, 3} else 2
    preferred_ok = (
        int(manual.get("id") or 0) == int(preferred_target["id"])
        and preferred_id == int(preferred_target["id"])
        and preferred_manual
        and int(paper.get("preferred_resource_id") or 0) == 0
        and not bool(int(paper.get("preferred_resource_manual") or 0))
        and lock_held_after_new_arrival
    )
    restored_expected_id = int((newest_published or published)["id"])
    return {
        "resource_set_integrity": check(len(h.storage.list_paper_resources(paper_id)) == expected_count, h.storage.list_paper_resources(paper_id)),
        "current_selection": check(
            automatic.get("file_type") == "published_version"
            and restored.get("file_type") == "published_version"
            and int(restored.get("id") or 0) == restored_expected_id,
            {"automatic": automatic, "restored": restored, "expected_restored_id": restored_expected_id},
        ),
        "preferred_selection": check(
            preferred_ok,
            {
                "manual": manual.get("id"),
                "target": preferred_target.get("id"),
                "preferred_before_clear": preferred_id,
                "preferred_after_clear": paper.get("preferred_resource_id"),
                "lock_held_after_new_arrival": lock_held_after_new_arrival,
            },
        ),
    }


def scenario_c08(h: Harness) -> dict[str, Any]:
    paper_id = h.add_work("multiple-roots")
    folder_a = h.storage.create_library_folder(parent_id=1, name=f"Project A {h.variant}")
    targets: list[dict[str, Any]] = []
    publication_expected = 0
    if h.variant == 0:
        folder_b = h.storage.create_library_folder(parent_id=1, name=f"Project B {h.variant}")
        targets = [folder_a, folder_b]
    elif h.variant == 1:
        space_a = h.storage.create_library_root_folder(name=f"Space A {h.variant}")
        targets = [folder_a, space_a]
    elif h.variant == 2:
        targets = [folder_a]
        publication_expected = 1
    else:
        space_a = h.storage.create_library_root_folder(name=f"Space A {h.variant}")
        space_b = h.storage.create_library_root_folder(name=f"Space B {h.variant}")
        targets = [space_a, space_b]
        publication_expected = 1
    for target in targets:
        h.storage.add_library_item(paper_id=paper_id, folder_id=int(target["id"]))
    if publication_expected:
        h.storage.add_my_publication(paper_id=paper_id)
    h.observe(
        "root_associations_created",
        {"target_folder_ids": [int(item["id"]) for item in targets], "my_publications": publication_expected},
    )
    primary = h.attach_pdf(
        paper_id,
        "shared-published.pdf",
        make_pdf_bytes(f"c08-{h.variant}"),
        version_role="version_of_record",
    )
    h.observe("primary_resource_attached", {"resource_id": int(primary["id"])})
    synced = ui_server.sync_all_pdf_aliases_for_paper(h.storage, paper_id)
    h.observe("multi_root_sync", synced)
    paper_count = int(h.storage.conn.execute("SELECT COUNT(*) FROM papers WHERE paper_id=?", (paper_id,)).fetchone()[0])
    item_count = int(h.storage.conn.execute("SELECT COUNT(*) FROM library_items WHERE paper_id=?", (paper_id,)).fetchone()[0])
    publication_count = int(h.storage.conn.execute("SELECT COUNT(*) FROM my_publications WHERE paper_id=?", (paper_id,)).fetchone()[0])
    resources = h.storage.list_paper_resources(paper_id)
    aliases = [item for item in filesystem_inventory([h.profile.library, h.profile.spaces, h.profile.publications]) if item.get("is_symlink")]
    return {
        "identity_uniqueness": check(paper_count == 1, paper_count),
        "association_multiplicity": check(item_count == len(targets) and publication_count == publication_expected, {"items": item_count, "targets": len(targets), "my_publications": publication_count, "publication_expected": publication_expected}),
        "path_mapping": check(not path_mapping_errors(h.storage, h.profile), {"errors": path_mapping_errors(h.storage, h.profile), "aliases": aliases, "sync": synced}),
    }


def scenario_c09(h: Harness) -> dict[str, Any]:
    paper_id = h.add_work("scoped-delete")
    folder_a = h.storage.create_library_folder(parent_id=1, name=f"Delete A {h.variant}")
    folder_b = h.storage.create_library_folder(parent_id=1, name=f"Keep B {h.variant}")
    first = h.storage.add_library_item(paper_id=paper_id, folder_id=int(folder_a["id"]))
    second = h.storage.add_library_item(paper_id=paper_id, folder_id=int(folder_b["id"]))
    author = h.storage.add_author_monitor(
        {
            "source_type": "google_scholar",
            "source_author_id": f"DELETEAUTHOR{h.variant}",
            "user_id": f"DELETEAUTHOR{h.variant}",
            "name": f"Delete Author {h.variant}",
            "url": f"https://scholar.google.com/citations?user=DELETEAUTHOR{h.variant}",
        }
    )
    h.storage.add_author_monitor_paper(author_monitor_id=int(author["id"]), paper_id=paper_id)
    publication = h.storage.add_my_publication(paper_id=paper_id)
    h.observe(
        "shared_relations_created",
        {
            "library_item_ids": [int(first["id"]), int(second["id"])],
            "author_monitor_id": int(author["id"]),
            "publication_id": int(publication["id"]),
        },
    )
    primary = h.attach_pdf(
        paper_id,
        "keep.pdf",
        make_pdf_bytes(f"c09-{h.variant}"),
        version_role="version_of_record",
    )
    attachment = ui_server.attach_file_to_paper(
        h.storage,
        paper_id=paper_id,
        filename="deletable-note.md",
        content=f"scoped deletion note {h.variant}".encode("utf-8"),
        file_role="note",
        added_via="benchmark_v4_retained_requirement",
    )
    h.observe(
        "resource_set_created",
        {"primary_resource_id": int(primary["id"]), "attachment_resource_id": int(attachment["id"])},
    )
    primary_path = Path(Storage.resource_local_path(primary))
    primary_hash = sha256_file(primary_path)
    h.observe("shared_state_before_delete")
    if h.variant == 0:
        h.storage.delete_library_item(item_id=int(first["id"]))
        deleted_scope = "library_item"
    elif h.variant == 1:
        h.storage.delete_author_monitor(int(author["id"]))
        deleted_scope = "author_monitor"
    elif h.variant == 2:
        h.storage.delete_my_publication(publication_id=int(publication["id"]))
        deleted_scope = "my_publication"
    else:
        ui_server.delete_paper_resource(h.storage, paper_id, int(attachment["id"]))
        deleted_scope = "nonprimary_resource"
    h.observe("scoped_relation_delete", {"scope": deleted_scope})
    remaining_items = h.storage.conn.execute("SELECT id FROM library_items WHERE paper_id=?", (paper_id,)).fetchall()
    remaining_author = int(h.storage.conn.execute("SELECT COUNT(*) FROM author_monitor_papers WHERE paper_id=?", (paper_id,)).fetchone()[0])
    remaining_publications = int(h.storage.conn.execute("SELECT COUNT(*) FROM my_publications WHERE paper_id=?", (paper_id,)).fetchone()[0])
    paper_exists = h.storage.get_paper(paper_id) is not None
    resource_exists = h.storage.get_paper_resource(int(primary["id"])) is not None
    attachment_exists = h.storage.get_paper_resource(int(attachment["id"])) is not None
    bytes_preserved = primary_path.exists() and sha256_file(primary_path) == primary_hash
    if h.variant == 0:
        relation_ok = (
            len(remaining_items) == 1
            and int(remaining_items[0]["id"]) == int(second["id"])
            and remaining_author == 1
            and remaining_publications == 1
        )
    elif h.variant == 1:
        relation_ok = remaining_author == 0 and len(remaining_items) == 2 and remaining_publications == 1
    elif h.variant == 2:
        relation_ok = remaining_publications == 0 and len(remaining_items) == 2 and remaining_author == 1
    else:
        relation_ok = not attachment_exists and len(remaining_items) == 2 and remaining_author == 1 and remaining_publications == 1
    resources = h.storage.list_paper_resources(paper_id)
    expected_resource_count = 1 if h.variant == 3 else 2
    return {
        "association_multiplicity": check(
            relation_ok,
            {
                "scope": deleted_scope,
                "remaining_items": [int(row["id"]) for row in remaining_items],
                "remaining_author_relations": remaining_author,
                "remaining_publications": remaining_publications,
            },
        ),
        "resource_set_integrity": check(
            resource_exists and bytes_preserved and len(resources) == expected_resource_count,
            {"resource_exists": resource_exists, "bytes_preserved": bytes_preserved, "resources": resources},
        ),
        "scoped_deletion": check(paper_exists and resource_exists and relation_ok, {"paper": paper_exists, "resource": resource_exists, "relations": relation_ok}),
        "no_unexpected_deletion": check(bytes_preserved, str(primary_path)),
    }


def scenario_c10(h: Harness) -> dict[str, Any]:
    paper_id = h.add_work("move-repair")
    source_folder = h.storage.create_library_folder(parent_id=1, name=f"Move Source {h.variant}")
    target_folder = h.storage.create_library_folder(parent_id=1, name=f"Move Target {h.variant}")
    item = h.storage.add_library_item(paper_id=paper_id, folder_id=int(source_folder["id"]))
    h.observe(
        "source_associations_created",
        {
            "source_folder_id": int(source_folder["id"]),
            "target_folder_id": int(target_folder["id"]),
            "library_item_id": int(item["id"]),
        },
    )
    primary = h.attach_pdf(
        paper_id,
        "original.pdf",
        make_pdf_bytes(f"c10-{h.variant}"),
        version_role="version_of_record",
    )
    note = ui_server.attach_file_to_paper(
        h.storage,
        paper_id=paper_id,
        filename="notes.md",
        content=b"state continuity note",
        file_role="note",
        added_via="benchmark_v4_retained_requirement",
    )
    h.observe("source_location")
    renamed = item
    paper = h.storage.get_paper(paper_id) or {}
    sync: dict[str, Any] = {}
    if h.variant in {0, 2, 3}:
        ui_server.move_or_alias_library_item_pdf(h.storage, item=item, target_folder_id=int(target_folder["id"]))
        h.storage.move_library_item(item_id=int(item["id"]), folder_id=int(target_folder["id"]))
        sync = ui_server.sync_all_pdf_aliases_for_paper(h.storage, paper_id)
        h.observe("move_to_target_folder", sync)
    if h.variant in {1, 2, 3}:
        renamed, paper, sync = ui_server.rename_library_item_and_sync_files(
            h.storage, item_id=int(item["id"]), name=f"Renamed Work {h.variant}"
        )
        h.observe("rename_and_sync", sync)
    if h.variant == 3:
        current = Path(str(paper.get("merged_pdf_path") or ""))
        external_name = current.with_name(f"externally-renamed-{h.variant}.pdf")
        current.rename(external_name)
        ui_server.update_paper_pdf_paths(h.storage, paper_id, external_name, message="benchmark path repair")
        ui_server.sync_all_pdf_aliases_for_paper(h.storage, paper_id, old_target=current, preserve_canonical_name=True)
        h.observe("external_rename_repair")
    resources = h.storage.list_paper_resources(paper_id)
    note_row = next(item for item in resources if int(item["id"]) == int(note["id"]))
    note_exists = Path(Storage.resource_local_path(note_row)).exists()
    return {
        "resource_set_integrity": check(len(resources) == 2 and note_exists, resources),
        "path_mapping": check(not path_mapping_errors(h.storage, h.profile), {"errors": path_mapping_errors(h.storage, h.profile), "renamed_item": renamed}),
        "no_orphan_db_references": check(not database_orphans(h.storage), database_orphans(h.storage)),
        "no_orphan_owned_files": check(not orphan_owned_files(h.storage, h.profile), orphan_owned_files(h.storage, h.profile)),
    }


def scenario_c11(h: Harness) -> dict[str, Any]:
    paper_id, _ = h.add_library_work("invalid-recovery")
    invalid_payloads = [
        b"<html><title>challenge</title></html>",
        b"",
        b"%PDF-1.7\ntruncated",
        b"<html>" + (b"x" * 1100) + b"%PDF-1.7\nmarker outside inspection window",
    ]
    invalid = invalid_payloads[h.variant]
    before_files = filesystem_inventory([h.profile.library, h.profile.associated, h.profile.pdfs])
    h.storage.update_download_status(paper_id, status="error", message=f"fixture failure {h.variant}")
    h.observe("failure_status_recorded")
    rejection = h.audit_product_rejection(
        "invalid_pdf_rejected",
        lambda: h.attach_pdf(
            paper_id,
            "invalid.pdf",
            invalid,
            version_role="version_of_record",
        ),
        "valid PDF|PDF|empty",
    )
    resources_after_failure = h.storage.list_paper_resources(paper_id, ensure_primary=False)
    valid = h.attach_pdf(
        paper_id,
        "recovered.pdf",
        make_pdf_bytes(f"c11-recovery-{h.variant}"),
        version_role="version_of_record",
    )
    h.observe("valid_retry_recovery")
    resources = h.storage.list_paper_resources(paper_id)
    current = h.storage.resolve_primary_paper_resource(paper_id) or {}
    after_files = filesystem_inventory([h.profile.library, h.profile.associated, h.profile.pdfs])
    rejection_ok = bool(rejection.get("rejected") and rejection.get("reason_matched"))
    return {
        "invalid_pdf_rejection": check(
            rejection_ok,
            {
                "product_outcome": rejection,
                "resources_after_invalid_input": resources_after_failure,
            },
        ),
        "resource_set_integrity": check(
            rejection_ok and not resources_after_failure and len(resources) == 1,
            {
                "product_outcome": rejection,
                "after_failure": resources_after_failure,
                "after_recovery": resources,
            },
        ),
        "current_selection": check(int(current.get("id") or 0) == int(valid["id"]), current),
        "exact_idempotence": check(rejection_ok and len(resources) == 1, resources),
        "no_orphan_db_references": check(not database_orphans(h.storage), database_orphans(h.storage)),
        "no_orphan_owned_files": check(not orphan_owned_files(h.storage, h.profile), {"orphans": orphan_owned_files(h.storage, h.profile), "before": before_files, "after": after_files}),
    }


def legacy_schema_text(commit):
    value = read_json(Path(__file__).resolve().parents[1] / 'fixtures' / 'legacy_schemas' / (commit + '.json'))
    return value['schema_sql'], value['schema_version'], value['source_sha256']


def create_legacy_database(profile: Profile, variant: int) -> dict[str, Any]:
    commit = LEGACY_COMMITS[variant]
    schema, version, source_hash = legacy_schema_text(commit)
    connection = sqlite3.connect(str(profile.db))
    try:
        connection.executescript(schema)
        timestamp = "2026-08-19T00:00:00+08:00"
        paper_id = f"legacy-schema-{version}"
        doi = f"10.9999/legacy.schema.{version}"
        pdf = profile.library / f"Legacy schema {version}.pdf"
        pdf.write_bytes(make_pdf_bytes(f"legacy-schema-{version}"))
        columns = {row[1] for row in connection.execute("PRAGMA table_info(papers)").fetchall()}
        values = {
            "paper_id": paper_id,
            "doi": doi,
            "title": f"Legacy schema {version} paper",
            "journal": "Legacy Benchmark Journal",
            "publication_date": "2025-01-01",
            "source": "legacy_fixture",
            "source_count": 1,
            "first_seen_at": timestamp,
            "last_seen_at": timestamp,
            "raw_json": "{}",
            "download_status": "success",
            "download_message": "legacy file retained",
            "main_pdf_path": str(pdf),
            "merged_pdf_path": str(pdf),
            "analysis_status": "not_started",
        }
        usable = {key: value for key, value in values.items() if key in columns}
        connection.execute(
            f"INSERT INTO papers ({','.join(usable)}) VALUES ({','.join('?' for _ in usable)})",
            tuple(usable.values()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO library_folders (id,name,parent_id,created_at,updated_at,sort_order) VALUES (1,'Library',NULL,?,?,0)",
            (timestamp, timestamp),
        )
        folder_id = 2
        connection.execute(
            "INSERT INTO library_folders (id,name,parent_id,created_at,updated_at,sort_order) VALUES (?,?,?,?,?,?)",
            (folder_id, f"Legacy Folder {version}", 1, timestamp, timestamp, 1),
        )
        if variant == 1:
            nested_id = 3
            connection.execute(
                "INSERT INTO library_folders (id,name,parent_id,created_at,updated_at,sort_order) VALUES (?,?,?,?,?,?)",
                (nested_id, "Nested Migration Folder", folder_id, timestamp, timestamp, 0),
            )
            folder_id = nested_id
        connection.execute(
            "INSERT INTO library_items (folder_id,paper_id,created_at,sort_order) VALUES (?,?,?,0)",
            (folder_id, paper_id, timestamp),
        )
        if variant in {1, 3}:
            connection.execute(
                "INSERT INTO my_publications (paper_id,sort_order,created_at,updated_at) VALUES (?,?,?,?)",
                (paper_id, 0, timestamp, timestamp),
            )

        fixture_files = [{"path": str(pdf), "sha256": sha256_file(pdf), "role": "primary"}]
        expected_resource_count = 1
        if variant >= 2:
            resource_columns = {row[1] for row in connection.execute("PRAGMA table_info(resources)").fetchall()}

            def insert_resource(path: Path, *, file_role: str, version_role: str, label: str) -> int:
                resource_values = {
                    "paper_id": paper_id,
                    "source_path": str(path),
                    "stored_path": str(path),
                    "original_filename": path.name,
                    "kind": "pdf",
                    "mime_type": "application/pdf",
                    "import_as": "primary_pdf" if file_role == "publication_version" else "attachment",
                    "size_bytes": path.stat().st_size,
                    "modified_at": timestamp,
                    "parse_status": "success",
                    "page_count": 1,
                    "display_name": path.name,
                    "file_role": file_role,
                    "version_role": version_role or None,
                    "version_label": label,
                    "storage_mode": "managed",
                    "sha256": sha256_file(path),
                    "added_via": "benchmark_legacy_fixture",
                    "missing_status": "",
                    "status": "imported",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                insertable = {key: value for key, value in resource_values.items() if key in resource_columns}
                cursor = connection.execute(
                    f"INSERT INTO resources ({','.join(insertable)}) VALUES ({','.join('?' for _ in insertable)})",
                    tuple(insertable.values()),
                )
                return int(cursor.lastrowid)

            primary_resource_id = insert_resource(
                pdf,
                file_role="publication_version",
                version_role="version_of_record",
                label="Published Version",
            )
            if "primary_resource_id" in columns:
                connection.execute(
                    "UPDATE papers SET primary_resource_id = ? WHERE paper_id = ?",
                    (primary_resource_id, paper_id),
                )
            if variant == 3:
                supplement = profile.associated / "Legacy schema 8 supplement.pdf"
                supplement.write_bytes(make_pdf_bytes("legacy-schema-8-supplement"))
                insert_resource(
                    supplement,
                    file_role="supplement",
                    version_role="",
                    label="Supplement",
                )
                fixture_files.append(
                    {"path": str(supplement), "sha256": sha256_file(supplement), "role": "supplement"}
                )
                expected_resource_count = 2
        connection.execute(f"PRAGMA user_version={version}")
        connection.commit()
        return {
            "commit": commit,
            "schema_version": version,
            "storage_source_sha256": source_hash,
            "paper_id": paper_id,
            "doi": doi,
            "pdf": str(pdf),
            "pdf_sha256": sha256_file(pdf),
            "folder_id": folder_id,
            "expected_resource_count": expected_resource_count,
            "fixture_files": fixture_files,
            "fixture_shape": variant_spec("C12_schema10_nondestructive_migration", variant)["structural_variant"],
        }
    finally:
        connection.close()


def scenario_c12(h: Harness) -> dict[str, Any]:
    legacy = h.state["legacy"]
    paper_id = legacy["paper_id"]
    h.paper_ids.append(paper_id)
    h.observe("product_opened_legacy_database", legacy)
    paper = h.storage.get_paper(paper_id) or {}
    resources = h.storage.list_paper_resources(paper_id)
    folder = h.storage.get_library_folder(int(legacy["folder_id"]))
    second_open_version = int(h.storage.conn.execute("PRAGMA user_version").fetchone()[0])
    pdf = Path(legacy["pdf"])
    files_preserved = all(
        Path(item["path"]).exists() and sha256_file(Path(item["path"])) == item["sha256"]
        for item in legacy["fixture_files"]
    )
    primary_rows = [resource for resource in resources if resource.get("is_primary")]
    resource_columns = {
        str(row["name"])
        for row in h.storage.conn.execute("PRAGMA table_info(resources)").fetchall()
    }
    paper_columns = {
        str(row["name"])
        for row in h.storage.conn.execute("PRAGMA table_info(papers)").fetchall()
    }
    flat_columns = {
        "file_type", "file_source", "source_detail", "annotation_state",
        "file_type_override", "annotation_override",
    }
    flat_schema_ok = (
        flat_columns.issubset(resource_columns)
        and "preferred_resource_manual" in paper_columns
        and bool(
            h.storage.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_identity_conflicts'"
            ).fetchone()
        )
        and bool(
            h.storage.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_source_observations'"
            ).fetchone()
        )
    )
    types_are_vnext = all(
        resource.get("file_type") in {
            "preprint", "accepted_manuscript", "published_version",
            "corrected_published_version", "correction_notice",
            "supplementary_material", "peer_review_file", "other", "unknown", "invalid_file",
        }
        and resource.get("annotation_state") in {"annotated", "unannotated", "unknown"}
        for resource in resources
    )
    return {
        "identity_uniqueness": check(int(h.storage.conn.execute("SELECT COUNT(*) FROM papers WHERE paper_id=?", (paper_id,)).fetchone()[0]) == 1, paper),
        "resource_set_integrity": check(
            len(resources) == int(legacy["expected_resource_count"]) and len(primary_rows) == 1,
            {"expected": legacy["expected_resource_count"], "resources": resources},
        ),
        "path_mapping": check(str(paper.get("merged_pdf_path") or "") == str(pdf) and not path_mapping_errors(h.storage, h.profile), {"paper": paper, "errors": path_mapping_errors(h.storage, h.profile)}),
        "no_unexpected_deletion": check(files_preserved and bool(folder), {"files": legacy["fixture_files"], "folder": folder}),
        "foreign_keys": check(not h.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), []),
        "restart_persistence": check(
            second_open_version == STORAGE_SCHEMA_VERSION and flat_schema_ok and types_are_vnext,
            {
                "schema_version": second_open_version,
                "flat_schema_ok": flat_schema_ok,
                "types_are_vnext": types_are_vnext,
                "resource_columns": sorted(resource_columns),
                "paper_columns": sorted(paper_columns),
            },
        ),
    }


def scenario_c13(h: Harness) -> dict[str, Any]:
    def resource_rows(paper_id: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in h.storage.conn.execute(
                """
                SELECT id, paper_id, stored_path, file_role, version_role
                FROM resources
                WHERE paper_id = ?
                ORDER BY id
                """,
                (paper_id,),
            ).fetchall()
        ]

    def library_relations(paper_id: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in h.storage.conn.execute(
                """
                SELECT id, paper_id, folder_id
                FROM library_items
                WHERE paper_id = ?
                ORDER BY id
                """,
                (paper_id,),
            ).fetchall()
        ]

    target_id, _ = h.add_library_work("target")
    source_id = h.add_work("standalone", doi=f"10.9999/standalone.{h.variant}")
    source_folder = h.storage.create_library_folder(parent_id=1, name=f"Standalone {h.variant}")
    source_item = h.storage.add_library_item(paper_id=source_id, folder_id=int(source_folder["id"]))
    source_dir = ui_server.local_copy_dir_for_library_folder(h.storage, int(source_folder["id"]))
    source_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(2 if h.variant in {1, 3} else 1):
        path = source_dir / f"standalone-{index}.{ 'dat' if index == 0 else 'txt'}"
        path.write_bytes(f"standalone payload {h.variant}-{index}".encode("utf-8"))
        paths.append(path)
        h.storage.create_paper_resource(
            paper_id=source_id,
            stored_path=str(path),
            display_name=path.name,
            file_role="other",
            added_via="loader",
            mime_type="application/octet-stream" if index == 0 else "text/plain",
            kind=path.suffix.lstrip("."),
        )
    h.observe(
        "standalone_objects_created",
        {
            "target_paper_id": target_id,
            "source_paper_id": source_id,
            "source_item_id": int(source_item["id"]),
            "resource_count": len(paths),
        },
    )
    if h.variant == 2:
        other_folder = h.storage.create_library_folder(parent_id=1, name="Other location")
        other_item = h.storage.add_library_item(paper_id=source_id, folder_id=int(other_folder["id"]))
        h.observe(
            "shared_source_precondition",
            {"other_folder_id": int(other_folder["id"]), "other_item_id": int(other_item["id"])},
        )
    source_resources_before = resource_rows(source_id)
    target_resources_before = resource_rows(target_id)
    source_relations_before = library_relations(source_id)
    target_relations_before = library_relations(target_id)
    h.observe(
        "standalone_before_merge",
        {
            "source_resources": source_resources_before,
            "target_resources": target_resources_before,
            "source_library_relations": source_relations_before,
            "target_library_relations": target_relations_before,
        },
    )
    before = sqlite_snapshot(h.profile.db)
    before_files = filesystem_inventory([h.profile.library, h.profile.associated])
    expected_rollback = h.variant in {2, 3}
    outcome = ""
    if h.variant == 2:
        try:
            ui_server.convert_library_item_to_paper_attachment(
                h.storage, source_item_id=int(source_item["id"]), target_paper_id=target_id
            )
        except Exception as exc:
            outcome = f"guarded:{type(exc).__name__}:{exc}"
        h.observe("shared_source_guard", outcome)
    elif h.variant == 3:
        real_move = shutil.move
        calls = {"count": 0, "failure_injected_at": 0}

        def fail_second_move(source: str, destination: str) -> str:
            calls["count"] += 1
            if calls["count"] == 2:
                calls["failure_injected_at"] = calls["count"]
                raise OSError("benchmark injected second-move failure")
            return str(real_move(source, destination))

        try:
            with patch.object(ui_server.shutil, "move", side_effect=fail_second_move):
                ui_server.convert_library_item_to_paper_attachment(
                    h.storage, source_item_id=int(source_item["id"]), target_paper_id=target_id
                )
        except Exception as exc:
            outcome = f"injected:{type(exc).__name__}:{exc}"
        h.observe(
            "injected_atomic_failure",
            {
                "outcome": outcome,
                "total_move_calls": calls["count"],
                "failure_injected_at": calls["failure_injected_at"],
                "rollback_move_calls": max(0, calls["count"] - calls["failure_injected_at"]),
            },
        )
    else:
        result = ui_server.convert_library_item_to_paper_attachment(
            h.storage, source_item_id=int(source_item["id"]), target_paper_id=target_id
        )
        outcome = f"success:{result['attached_count']}"
        h.observe("standalone_merged", result)
    after = sqlite_snapshot(h.profile.db)
    after_files = filesystem_inventory([h.profile.library, h.profile.associated])
    source_resources = resource_rows(source_id)
    target_resources = resource_rows(target_id)
    source_relations = library_relations(source_id)
    target_relations = library_relations(target_id)
    if expected_rollback:
        source_present = h.storage.get_paper(source_id) is not None
        source_item_present = h.storage.get_library_item(int(source_item["id"])) is not None
        source_paths_present = all(path.exists() for path in paths)
        state_unchanged = normalized_state(before) == normalized_state(after)
        files_unchanged = before_files == after_files
        expected_failure_observed = (
            outcome.startswith("guarded:ValueError:")
            and "other Library locations" in outcome
            if h.variant == 2
            else calls["failure_injected_at"] == 2
            and "benchmark injected second-move failure" in outcome
        )
        rollback_ok = (
            expected_failure_observed
            and state_unchanged
            and files_unchanged
        )
        resource_ok = (
            source_present
            and source_item_present
            and source_paths_present
            and source_resources == source_resources_before
            and len(source_resources) == len(paths)
            and not target_resources
            and not target_resources_before
        )
        expected_source_relation_count = 2 if h.variant == 2 else 1
        scoped_ok = (
            len(source_relations_before) == expected_source_relation_count
            and source_relations == source_relations_before
            and len(source_relations) == expected_source_relation_count
            and target_relations == target_relations_before
        )
    else:
        source_present = h.storage.get_paper(source_id) is not None
        source_item_present = h.storage.get_library_item(int(source_item["id"])) is not None
        resource_ok = (
            not source_resources
            and len(target_resources) == len(paths)
            and {str(item.get("stored_path") or "") for item in target_resources}
            != {str(item.get("stored_path") or "") for item in target_resources_before}
        )
        rollback_ok = True
        scoped_ok = (
            not source_present
            and not source_item_present
            and not source_relations
            and target_relations == target_relations_before
        )
    return {
        "identity_uniqueness": check(int(h.storage.conn.execute("SELECT COUNT(*) FROM papers WHERE paper_id=?", (target_id,)).fetchone()[0]) == 1, target_id),
        "resource_set_integrity": check(
            resource_ok,
            {
                "outcome": outcome,
                "source_resources_before": source_resources_before,
                "source_resources_after": source_resources,
                "target_resources_before": target_resources_before,
                "target_resources_after": target_resources,
                "expected_source_resource_count_after_rollback": (
                    len(paths) if expected_rollback else 0
                ),
                "expected_target_resource_count": 0 if expected_rollback else len(paths),
            },
        ),
        "path_mapping": check(not path_mapping_errors(h.storage, h.profile), {"errors": path_mapping_errors(h.storage, h.profile), "before_files": before_files, "after_files": after_files}),
        "scoped_deletion": check(
            scoped_ok,
            {
                "source_present": source_present,
                "source_item_present": source_item_present,
                "source_relation_count_before": len(source_relations_before),
                "source_relation_count_after": len(source_relations),
                "expected_source_relation_count_after": (
                    (2 if h.variant == 2 else 1) if expected_rollback else 0
                ),
                "source_relations_before": source_relations_before,
                "source_relations_after": source_relations,
                "target_relation_count_before": len(target_relations_before),
                "target_relation_count_after": len(target_relations),
                "target_relations_before": target_relations_before,
                "target_relations_after": target_relations,
                "target_relation_added": target_relations != target_relations_before,
            },
        ),
        "no_unexpected_deletion": check(all(path.exists() for path in paths) if expected_rollback else all(Path(Storage.resource_local_path(item)).exists() for item in target_resources), outcome),
        "rollback_integrity": check(
            rollback_ok,
            {
                "outcome": outcome,
                "expected_failure_observed": expected_failure_observed if expected_rollback else True,
                "total_move_calls": calls["count"] if h.variant == 3 else None,
                "failure_injected_at": calls["failure_injected_at"] if h.variant == 3 else None,
                "rollback_move_calls": (
                    max(0, calls["count"] - calls["failure_injected_at"])
                    if h.variant == 3
                    else None
                ),
                "state_unchanged": state_unchanged if expected_rollback else None,
                "files_unchanged": files_unchanged if expected_rollback else None,
                "before": normalized_state(before),
                "after": normalized_state(after),
            },
        ),
    }


SCENARIO_FUNCTIONS: dict[str, Callable[[Harness], dict[str, Any]]] = {
    "C01_three_entry_same_work": scenario_c01,
    "C02_preprint_to_vor": scenario_c02,
    "C03_accepted_to_published": scenario_c03,
    "C04_byte_identical_refresh": scenario_c04,
    "C05_clean_annotated_same_content": scenario_c05,
    "C06_nonpublication_never_current": scenario_c06,
    "C07_manual_preferred_then_auto": scenario_c07,
    "C08_multiple_roots": scenario_c08,
    "C09_scoped_relation_deletion": scenario_c09,
    "C10_move_rename_repair_restart": scenario_c10,
    "C11_invalid_failure_recovery": scenario_c11,
    "C12_schema10_nondestructive_migration": scenario_c12,
    "C13_standalone_merge_and_rollback": scenario_c13,
}


def add_global_checks(
    storage: Storage,
    profile: Profile,
    family: dict[str, Any],
    checks: dict[str, Any],
) -> None:
    applicable = set(family["applicable"])
    foreign_keys = [dict(row) for row in storage.conn.execute("PRAGMA foreign_key_check").fetchall()]
    if "foreign_keys" in applicable:
        checks["foreign_keys"] = check(not foreign_keys, foreign_keys)
    if "no_orphan_db_references" in applicable:
        orphans = database_orphans(storage)
        checks["no_orphan_db_references"] = check(not orphans, orphans)
    if "no_orphan_owned_files" in applicable:
        files = orphan_owned_files(storage, profile)
        checks["no_orphan_owned_files"] = check(not files, files)
    if "path_mapping" in applicable and "path_mapping" not in checks:
        errors = path_mapping_errors(storage, profile)
        checks["path_mapping"] = check(not errors, errors)


def observation_surface_errors(event: dict[str, Any]) -> list[str]:
    """Fail closed on empty evidence and API/SQLite disagreement."""

    errors: list[str] = []
    for key in ("ui", "api", "sqlite", "filesystem"):
        if key not in event or event.get(key) is None:
            errors.append(f"missing {key} evidence")
    ui = event.get("ui") or {}
    if not isinstance(ui, dict):
        errors.append("malformed UI evidence")
    else:
        if not re.fullmatch(r"[0-9a-f]{64}", str(ui.get("root_html_sha256") or "")):
            errors.append("missing valid rendered-root HTML hash")
        for key in ("library_bootstrap", "library_navigation", "my_publications"):
            if not isinstance(ui.get(key), dict):
                errors.append(f"missing UI backing state: {key}")
    api = event.get("api") or {}
    if not isinstance(api, dict) or not ((api.get("health") or {}).get("ok")):
        errors.append("API health readback failed")
    sqlite_evidence = event.get("sqlite") or {}
    if not isinstance(sqlite_evidence, dict):
        errors.append("malformed SQLite evidence")
        tables: dict[str, Any] = {}
    else:
        if int(sqlite_evidence.get("user_version") or 0) != STORAGE_SCHEMA_VERSION:
            errors.append(f"SQLite evidence is not schema {STORAGE_SCHEMA_VERSION}")
        if sqlite_evidence.get("foreign_key_check") != []:
            errors.append("SQLite foreign-key check failed")
        if sqlite_evidence.get("integrity_check") != ["ok"]:
            errors.append("SQLite integrity check failed")
        tables = sqlite_evidence.get("tables") or {}
        if not isinstance(tables, dict):
            errors.append("SQLite table-state evidence is missing")
            tables = {}
    if not isinstance(event.get("filesystem"), list):
        errors.append("malformed filesystem evidence")
    if not isinstance(api, dict):
        return errors
    papers = tables.get("papers") or []
    resources = tables.get("resources") or []
    if not isinstance(papers, list) or not isinstance(resources, list):
        errors.append("malformed SQLite paper/resource tables")
        return errors
    resources_by_paper: dict[str, list[dict[str, Any]]] = {}
    for resource in resources:
        if not isinstance(resource, dict):
            errors.append("malformed SQLite resource row")
            continue
        resources_by_paper.setdefault(str(resource.get("paper_id") or ""), []).append(resource)
    restart = event.get("event_type") == "restart_observation"
    for paper in papers:
        if not isinstance(paper, dict) or not str(paper.get("paper_id") or ""):
            errors.append("malformed SQLite paper row")
            continue
        paper_id = str(paper["paper_id"])
        payload = api.get(paper_id)
        if not isinstance(payload, dict) or payload.get("error"):
            errors.append(f"API lacks readable state for SQLite paper {paper_id}")
            continue
        files_payload = payload if restart else payload.get("files")
        if not isinstance(files_payload, dict) or files_payload.get("paper_id") != paper_id:
            errors.append(f"paper-files API identity mismatch for {paper_id}")
            continue
        for key in ("primary_resource_id", "preferred_resource_id"):
            if int(files_payload.get(key) or 0) != int(paper.get(key) or 0):
                errors.append(f"paper-files/SQLite {key} mismatch for {paper_id}")
        if not restart:
            paper_envelope = payload.get("paper") or {}
            paper_payload = paper_envelope.get("paper") if isinstance(paper_envelope, dict) else None
            if not isinstance(paper_payload, dict) or paper_payload.get("paper_id") != paper_id:
                errors.append(f"paper API identity mismatch for {paper_id}")
            else:
                for key in ("primary_resource_id", "preferred_resource_id"):
                    if int(paper_payload.get(key) or 0) != int(paper.get(key) or 0):
                        errors.append(f"paper API/SQLite {key} mismatch for {paper_id}")
        api_files = files_payload.get("files")
        if not isinstance(api_files, list):
            errors.append(f"malformed paper-files API list for {paper_id}")
            continue
        api_by_id = {
            int(item.get("id") or 0): item
            for item in api_files
            if isinstance(item, dict) and int(item.get("id") or 0)
        }
        raw_db_by_id = {
            int(item.get("id") or 0): item
            for item in resources_by_paper.get(paper_id, [])
            if int(item.get("id") or 0)
        }
        visibility = expected_paper_resource_visibility(
            paper,
            list(raw_db_by_id.values()),
        )
        db_by_id = {
            int(item.get("id") or 0): item
            for item in visibility["visible"]
            if int(item.get("id") or 0)
        }
        if set(api_by_id) != set(db_by_id):
            errors.append(
                "paper-files/product-visible SQLite resource-id set mismatch for "
                f"{paper_id}; api={sorted(api_by_id)} visible={sorted(db_by_id)} "
                f"intentionally_hidden={visibility['hidden_ids']}"
            )
            continue
        for resource_id, db_resource in db_by_id.items():
            api_resource = api_by_id[resource_id]
            comparisons = {
                "paper_id": (str(api_resource.get("paper_id") or ""), str(db_resource.get("paper_id") or "")),
                "file_role": (str(api_resource.get("file_role") or "other"), str(db_resource.get("file_role") or "other")),
                "version_role": (str(api_resource.get("version_role") or ""), str(db_resource.get("version_role") or "")),
                "sha256": (str(api_resource.get("sha256") or ""), str(db_resource.get("sha256") or "")),
                "content_sha256": (str(api_resource.get("content_sha256") or ""), str(db_resource.get("content_sha256") or "")),
                "local_path": (
                    str(api_resource.get("local_path") or ""),
                    str(db_resource.get("stored_path") or db_resource.get("source_path") or ""),
                ),
            }
            for key, (api_value, db_value) in comparisons.items():
                if api_value != db_value:
                    errors.append(f"paper-files/SQLite resource {resource_id} {key} mismatch")
            if int(api_resource.get("annotation_count") or 0) != int(db_resource.get("annotation_count") or 0):
                errors.append(f"paper-files/SQLite resource {resource_id} annotation_count mismatch")
            if bool(api_resource.get("is_primary")) != (
                resource_id == int(paper.get("primary_resource_id") or 0)
            ):
                errors.append(f"paper-files primary marker mismatch for resource {resource_id}")
            if bool(api_resource.get("is_preferred")) != (
                resource_id == int(paper.get("preferred_resource_id") or 0)
            ):
                errors.append(f"paper-files preferred marker mismatch for resource {resource_id}")
    return errors


def audit_trace_surfaces(trace_path: Path, required_steps: list[str]) -> dict[str, Any]:
    """Verify that locked transitions have consistent UI/API/SQLite/filesystem evidence."""

    transition_events: list[dict[str, Any]] = []
    restart_events: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            event = json.loads(raw)
            if event.get("event_type") == "state_transition_observation":
                transition_events.append(event)
            elif event.get("event_type") == "restart_observation":
                restart_events.append(event)
    observed_steps = [str(event.get("step") or "") for event in transition_events]
    missing_steps = [step for step in required_steps if step not in observed_steps]
    surface_errors: list[dict[str, Any]] = []
    for event in transition_events:
        content_errors = observation_surface_errors(event)
        if content_errors:
            surface_errors.append(
                {"step": event.get("step"), "errors": content_errors}
            )
    if len(restart_events) != 1:
        surface_errors.append(
            {"step": "restart_observation", "error": f"expected one event, found {len(restart_events)}"}
        )
    else:
        restart_errors = observation_surface_errors(restart_events[0])
        if restart_errors:
            surface_errors.append(
                {"step": "restart_observation", "errors": restart_errors}
            )
    return {
        "status": "pass" if not missing_steps and not surface_errors else "fail",
        "evidence": {
            "required_steps": required_steps,
            "observed_steps": observed_steps,
            "missing_required_steps": missing_steps,
            "transition_event_count": len(transition_events),
            "restart_event_count": len(restart_events),
            "surface_errors": surface_errors,
        },
    }


def register_legacy_precondition(harness: Harness, legacy: dict[str, Any]) -> None:
    """Expose an already-migrated legacy paper to the first four-surface readback.

    ``Storage(profile.db)`` opens and migrates the old fixture before the API
    server starts.  The generic initial observation must therefore request the
    migrated paper from the API as well as reading it from SQLite; otherwise
    the cross-surface auditor sees a SQLite paper with no corresponding API
    payload and correctly fails the pilot.
    """

    paper_id = str(legacy.get("paper_id") or "")
    if not paper_id:
        raise RuntimeError("Legacy migration fixture lacks a paper_id")
    harness.state["legacy"] = legacy
    if paper_id not in harness.paper_ids:
        harness.paper_ids.append(paper_id)


def run_fixture(
    parent: Profile,
    family: dict[str, Any],
    variant: int,
    fixture_index: int,
    base_port: int,
) -> dict[str, Any]:
    fixture_id = f"{family['id']}_V{variant + 1:02d}"
    structure = variant_spec(family["id"], variant)
    profile = fixture_profile(parent, fixture_id)
    trace = HashChainJsonl(profile.traces / "actions.jsonl")
    legacy: dict[str, Any] | None = None
    if family["id"] == "C12_schema10_nondestructive_migration":
        legacy = create_legacy_database(profile, variant)
        write_json_new(profile.outputs / "legacy_fixture_manifest.json", legacy)
    port = 0
    restart_port = 0
    assert_port_available(port)
    assert_port_available(restart_port)
    started_at = utc_now()
    checks: dict[str, Any] = {}
    status = "completed"
    error = ""
    before_restart: dict[str, Any] | None = None
    after_restart: dict[str, Any] | None = None
    operations = 0
    observed_steps: list[str] = []
    with patched_product_roots(profile):
        storage = Storage(profile.db)
        if int(storage.conn.execute("PRAGMA user_version").fetchone()[0]) != STORAGE_SCHEMA_VERSION:
            storage.close()
            raise RuntimeError(f"Fixture database did not reach schema {STORAGE_SCHEMA_VERSION}")
        try:
            with ApiServer(profile, port) as api:
                harness = Harness(
                    parent=parent,
                    profile=profile,
                    family=family,
                    variant=variant,
                    structural_variant=structure["structural_variant"],
                    code_path_tags=structure["code_path_tags"],
                    api=api,
                    storage=storage,
                    trace=trace,
                )
                if legacy:
                    register_legacy_precondition(harness, legacy)
                harness.observe("initial_state")
                try:
                    checks = SCENARIO_FUNCTIONS[family["id"]](harness)
                    add_global_checks(storage, profile, family, checks)
                    harness.observe("pre_restart_final_state", {"checks": checks})
                except Exception as exc:
                    status = "exception"
                    error = f"{type(exc).__name__}: {exc}"
                    trace.append(
                        {
                            "event_type": "fixture_exception",
                            "run_id": parent.run_id,
                            "fixture_id": fixture_id,
                            "family_id": family["id"],
                            "variant": variant,
                            "error": error,
                        }
                    )
                operations = harness.operations
                observed_steps = list(harness.observed_steps)
                before_restart = sqlite_snapshot(profile.db)
        finally:
            storage.close()
        reopened: Storage | None = None
        try:
            reopened = Storage(profile.db)
            with ApiServer(profile, restart_port) as restarted_api:
                api_after: dict[str, Any] = {"health": restarted_api.get_json("/api/health")}
                ui_after: dict[str, Any] = {
                    "root_html_sha256": sha256_bytes(restarted_api.get_text("/").encode("utf-8")),
                    "library_bootstrap": restarted_api.get_json("/api/library/bootstrap"),
                    "library_navigation": restarted_api.get_json("/api/library"),
                    "my_publications": restarted_api.get_json("/api/my-publications"),
                }
                paper_ids = [row["paper_id"] for row in reopened.conn.execute("SELECT paper_id FROM papers ORDER BY paper_id").fetchall()]
                for paper_id in paper_ids:
                    api_after[paper_id] = restarted_api.get_json("/api/paper-files", {"paper_id": paper_id})
                    ui_after.setdefault("paper_locations", {})[paper_id] = restarted_api.get_json(
                        "/api/library/paper-locations", {"paper_id": paper_id}
                    )
                after_restart = sqlite_snapshot(profile.db)
                trace.append(
                    {
                        "event_type": "restart_observation",
                        "run_id": parent.run_id,
                        "fixture_id": fixture_id,
                        "family_id": family["id"],
                        "variant": variant,
                        "ui": ui_after,
                        "api": api_after,
                        "sqlite": after_restart,
                        "filesystem": filesystem_inventory(
                            [profile.library, profile.spaces, profile.publications, profile.associated, profile.pdfs, profile.trash]
                        ),
                    }
                )
                if "restart_persistence" in family["applicable"]:
                    stable = normalized_state(before_restart or {}) == normalized_state(after_restart)
                    existing = checks.get("restart_persistence")
                    if existing and existing.get("status") != "pass":
                        stable = False
                    checks["restart_persistence"] = check(
                        stable,
                        {
                            "before_sha256": sha256_bytes(json.dumps(normalized_state(before_restart or {}), sort_keys=True, default=str).encode()),
                            "after_sha256": sha256_bytes(json.dumps(normalized_state(after_restart), sort_keys=True, default=str).encode()),
                            "scenario_check": existing,
                        },
                    )
        finally:
            if reopened is not None:
                reopened.close()

    applicable = list(family["applicable"])
    for invariant in applicable:
        if invariant not in checks:
            checks[invariant] = {
                "status": "coverage_gap",
                "evidence": f"Runner did not produce the locked {invariant} composite for this family",
            }
    unexpected_checks = sorted(set(checks) - set(applicable))
    for invariant in unexpected_checks:
        checks[invariant]["not_in_locked_matrix"] = True
    required_steps = list(structure["required_steps"])
    missing_required_steps = [step for step in required_steps if step not in observed_steps]
    try:
        unobserved_surface = audit_trace_surfaces(trace.path, required_steps)
    except Exception as exc:
        unobserved_surface = {
            "status": "fail",
            "evidence": {
                "required_steps": required_steps,
                "observed_steps": observed_steps,
                "missing_required_steps": missing_required_steps,
                "audit_error": f"{type(exc).__name__}: {exc}",
            },
        }
    complete_success = status == "completed" and all(
        checks[invariant].get("status") == "pass" for invariant in applicable
    ) and not missing_required_steps and unobserved_surface.get("status") == "pass"
    result = {
        "schema_version": current_benchmark_schema_version(),
        "run_id": parent.run_id,
        "fixture_id": fixture_id,
        "family_id": family["id"],
        "variant": variant,
        "structural_variant": structure["structural_variant"],
        "code_path_tags": structure["code_path_tags"],
        "required_steps": required_steps,
        "observed_steps": observed_steps,
        "missing_required_steps": missing_required_steps,
        "unobserved_surface": unobserved_surface,
        "fixture_profile": str(profile.root),
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": status,
        "error": error,
        "operations_observed": operations,
        "applicable_invariants": applicable,
        "invariants": checks,
        "complete_success": complete_success,
        "trace_audit": trace.audit(),
        "database_sha256": sha256_file(profile.db),
        "sqlite_before_restart_sha256": sha256_bytes(json.dumps(normalized_state(before_restart or {}), sort_keys=True, default=str).encode()),
        "sqlite_after_restart_sha256": sha256_bytes(json.dumps(normalized_state(after_restart or {}), sort_keys=True, default=str).encode()),
    }
    write_json_new(profile.outputs / "fixture_result.json", result)
    return result
