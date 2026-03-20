from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import py_sec_edgar.lookup as lookup_module
from py_sec_edgar.config import load_config
from py_sec_edgar.lookup import (
    local_lookup_artifacts_path,
    local_lookup_filings_all_path,
    local_lookup_filings_path,
    register_local_filings_in_lookup,
    refresh_local_lookup_indexes,
)


def _write_merged_index(config, rows: list[dict]) -> None:
    config.ensure_runtime_dirs()
    pd.DataFrame(rows).to_parquet(config.merged_index_path, index=False)


def _create_local_submission_and_extracted(config, filename: str, extracted_files: list[str]) -> None:
    relative = filename.lstrip("/")
    submission_path = config.download_root / Path(relative)
    submission_path.parent.mkdir(parents=True, exist_ok=True)
    submission_path.write_text("submission", encoding="utf-8")

    extracted_dir = submission_path.parent / submission_path.stem.replace("-", "")
    extracted_dir.mkdir(parents=True, exist_ok=True)
    for name in extracted_files:
        out = extracted_dir / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("artifact", encoding="utf-8")


def _seed_duplicate_accession_fixture(config) -> list[dict]:
    rows = [
        {
            "CIK": "320193",
            "Form Type": "SC 13D",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/320193/0000320193-25-000010.txt",
        },
        {
            "CIK": "999999",
            "Form Type": "SC 13D/A",
            "Date Filed": "2025-01-16",
            "Filename": "edgar/data/999999/0000320193-25-000010.txt",
        },
        {
            "CIK": "789019",
            "Form Type": "4",
            "Date Filed": "2025-02-10",
            "Filename": "edgar/data/789019/0000789019-25-000123.txt",
        },
    ]
    _write_merged_index(config, rows)
    _create_local_submission_and_extracted(
        config,
        rows[0]["Filename"],
        extracted_files=["primary_doc.xml", "shared.xml"],
    )
    _create_local_submission_and_extracted(
        config,
        rows[1]["Filename"],
        extracted_files=["secondary_doc.xml", "shared.xml"],
    )
    return rows


def test_refresh_local_lookup_indexes_local_only_excludes_non_local_and_dedupes(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    rows = _seed_duplicate_accession_fixture(config)
    filing_parties = pd.DataFrame(
        [
            {"accession_number": "0000320193-25-000010", "party_role": "issuer"},
            {"accession_number": "0000320193-25-000010", "party_role": "reporting_owner"},
        ]
    )
    filing_parties.to_parquet(config.normalized_refdata_root / "filing_parties.parquet", index=False)

    result = refresh_local_lookup_indexes(config)
    assert result["filings_row_count"] == 1
    assert result["artifacts_row_count"] == 6
    assert result["placement_row_count"] == 3
    assert result["local_placement_row_count"] == 2
    assert result["deduped_local_filing_row_count"] == 1
    assert result["deduped_global_filing_row_count"] == 0
    assert result["scanned_extracted_dir_count"] == 3
    assert result["global_filings_index_written"] is False
    assert not local_lookup_filings_all_path(config).exists()

    filings = pd.read_parquet(local_lookup_filings_path(config))
    assert len(filings.index) == 1
    row = filings.iloc[0]
    assert row["accession_number"] == "0000320193-25-000010"
    assert bool(row["submission_exists"]) is True
    assert int(row["local_submission_path_count"]) == 2
    assert int(row["submission_path_count"]) == 2
    assert int(row["local_extracted_dir_count"]) == 2
    assert int(row["local_artifact_file_count"]) == 4
    assert int(row["extracted_file_count"]) == 4
    assert bool(row["has_extracted_artifacts"]) is True
    assert int(row["filing_party_record_count_max"]) == 2
    # Explicitly lock accession-level MAX semantics, not SUM.
    assert int(row["filing_party_record_count_max"]) != 4
    assert int(row["filing_party_record_count"]) == 2
    assert bool(row["has_filing_parties"]) is True

    # Deterministic representative row: canonical row is smallest submission_path.
    expected_submission = str(config.download_root / rows[0]["Filename"])
    expected_extracted_dir = str((config.download_root / rows[0]["Filename"]).parent / "000032019325000010")
    assert row["submission_path"] == expected_submission
    assert row["filename"] == rows[0]["Filename"]
    assert row["filing_cik"] == "0000320193"
    assert row["form_type"] == "SC 13D"
    assert row["filing_date"] == "2025-01-15"
    assert row["extracted_dir_path"] == expected_extracted_dir

    artifacts = pd.read_parquet(local_lookup_artifacts_path(config))
    assert len(artifacts.index) == 6
    assert artifacts["artifact_type"].value_counts().to_dict() == {"extracted": 4, "submission": 2}
    assert set(artifacts["source_filename"].tolist()) == {rows[0]["Filename"], rows[1]["Filename"]}


def test_refresh_local_lookup_indexes_writes_global_when_requested(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _seed_duplicate_accession_fixture(config)

    result = refresh_local_lookup_indexes(config, include_global_filings=True)
    assert result["global_filings_index_written"] is True
    assert result["global_filings_row_count"] == 2
    assert result["deduped_global_filing_row_count"] == 2
    assert local_lookup_filings_all_path(config).exists()

    local_filings = pd.read_parquet(local_lookup_filings_path(config))
    global_filings = pd.read_parquet(local_lookup_filings_all_path(config))
    assert len(local_filings.index) == 1
    assert len(global_filings.index) == 2
    non_local = global_filings[global_filings["accession_number"] == "0000789019-25-000123"].iloc[0]
    assert bool(non_local["submission_exists"]) is False
    assert int(non_local["local_submission_path_count"]) == 0
    assert int(non_local["submission_path_count"]) == 0
    assert int(non_local["local_extracted_dir_count"]) == 0
    assert int(non_local["local_artifact_file_count"]) == 0
    assert int(non_local["extracted_file_count"]) == 0


def test_refresh_local_lookup_indexes_is_deterministic_on_rebuild(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _seed_duplicate_accession_fixture(config)

    refresh_local_lookup_indexes(config, include_global_filings=True)
    first_local = pd.read_parquet(local_lookup_filings_path(config))
    first_global = pd.read_parquet(local_lookup_filings_all_path(config))
    first_artifacts = pd.read_parquet(local_lookup_artifacts_path(config))

    refresh_local_lookup_indexes(config, include_global_filings=True)
    second_local = pd.read_parquet(local_lookup_filings_path(config))
    second_global = pd.read_parquet(local_lookup_filings_all_path(config))
    second_artifacts = pd.read_parquet(local_lookup_artifacts_path(config))

    pd.testing.assert_frame_equal(first_local, second_local)
    pd.testing.assert_frame_equal(first_global, second_global)
    pd.testing.assert_frame_equal(first_artifacts, second_artifacts)


def test_refresh_local_lookup_indexes_uses_alternate_root_paths(tmp_path: Path) -> None:
    config = load_config(tmp_path / "alt_project")
    _seed_duplicate_accession_fixture(config)
    result = refresh_local_lookup_indexes(config)
    assert str(tmp_path / "alt_project") in result["filings_index_path"]
    assert str(tmp_path / "alt_project") in result["artifacts_index_path"]


def test_refresh_local_lookup_indexes_fails_cleanly_when_merged_index_columns_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config.merged_index_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"CIK": "320193", "Filename": "edgar/data/320193/a.txt"}]).to_parquet(
        config.merged_index_path,
        index=False,
    )

    with pytest.raises(ValueError, match="missing required columns"):
        refresh_local_lookup_indexes(config)


def test_refresh_scans_each_extracted_dir_once_for_repeated_rows(monkeypatch, tmp_path: Path) -> None:
    config = load_config(tmp_path)
    rows = [
        {
            "CIK": "320193",
            "Form Type": "SC 13D",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/320193/0000320193-25-000010.txt",
        },
        {
            "CIK": "320193",
            "Form Type": "SC 13D",
            "Date Filed": "2025-01-15",
            "Filename": "edgar/data/320193/0000320193-25-000010.txt",
        },
    ]
    _write_merged_index(config, rows)
    _create_local_submission_and_extracted(config, rows[0]["Filename"], extracted_files=["primary_doc.xml"])

    calls: list[str] = []
    original_list_files = lookup_module._list_files

    def spy(path: Path) -> list[str]:
        calls.append(str(path))
        return original_list_files(path)

    monkeypatch.setattr(lookup_module, "_list_files", spy)
    result = refresh_local_lookup_indexes(config)

    assert result["placement_row_count"] == 2
    assert result["scanned_extracted_dir_count"] == 1
    assert len(calls) == 1


def test_register_local_filings_in_lookup_writes_filings_and_artifacts(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    rows = _seed_duplicate_accession_fixture(config)

    result = register_local_filings_in_lookup(
        config,
        warmed_filenames=[rows[0]["Filename"]],
        warmed_accession_numbers=["0000320193-25-000010"],
    )
    assert result["safe_to_use"] is True
    assert result["matched_merged_rows_count"] == 2
    assert result["registered_filing_row_count"] == 1
    assert result["registered_artifact_row_count"] == 6

    filings = pd.read_parquet(local_lookup_filings_path(config))
    artifacts = pd.read_parquet(local_lookup_artifacts_path(config))

    assert len(filings.index) == 1
    row = filings.iloc[0]
    assert row["accession_number"] == "0000320193-25-000010"
    assert int(row["local_submission_path_count"]) == 2
    assert int(row["submission_path_count"]) == 2
    assert int(row["local_artifact_file_count"]) == 4
    assert int(row["extracted_file_count"]) == 4
    assert bool(row["has_extracted_artifacts"]) is True
    assert len(artifacts.index) == 6
    assert artifacts["artifact_type"].value_counts().to_dict() == {"extracted": 4, "submission": 2}


def test_register_local_filings_in_lookup_rerun_is_deterministic_and_deduped(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    rows = _seed_duplicate_accession_fixture(config)

    first = register_local_filings_in_lookup(
        config,
        warmed_filenames=[rows[0]["Filename"]],
        warmed_accession_numbers=["0000320193-25-000010"],
    )
    assert first["safe_to_use"] is True
    first_filings = pd.read_parquet(local_lookup_filings_path(config))
    first_artifacts = pd.read_parquet(local_lookup_artifacts_path(config))

    second = register_local_filings_in_lookup(
        config,
        warmed_filenames=[rows[0]["Filename"]],
        warmed_accession_numbers=["0000320193-25-000010"],
    )
    assert second["safe_to_use"] is True
    second_filings = pd.read_parquet(local_lookup_filings_path(config))
    second_artifacts = pd.read_parquet(local_lookup_artifacts_path(config))

    assert len(second_filings.index) == 1
    assert len(second_artifacts.index) == 6
    pd.testing.assert_frame_equal(first_filings, second_filings)
    pd.testing.assert_frame_equal(first_artifacts, second_artifacts)


def test_register_local_filings_in_lookup_marks_unsafe_when_unmatched_input(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    _seed_duplicate_accession_fixture(config)

    result = register_local_filings_in_lookup(
        config,
        warmed_filenames=["edgar/data/does-not-exist/0000000000-00-000000.txt"],
        warmed_accession_numbers=["0000000000-00-000000"],
    )
    assert result["safe_to_use"] is False
    assert result["matched_merged_rows_count"] == 0
    assert result["skipped_count"] >= 1
    assert "filename_not_found_in_merged_index" in result["skip_reasons"]
