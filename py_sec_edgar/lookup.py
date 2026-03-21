from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Callable, Iterable

import pandas as pd

from py_sec_edgar.config import AppConfig
from py_sec_edgar.refdata.normalize import normalize_cik


_MERGED_IDX_REQUIRED_COLUMNS = {"CIK", "Form Type", "Date Filed", "Filename"}
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")


def local_lookup_filings_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "local_lookup_filings.parquet"


def local_lookup_artifacts_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "local_lookup_artifacts.parquet"


def local_lookup_filings_all_path(config: AppConfig) -> Path:
    return config.normalized_refdata_root / "local_lookup_filings_all.parquet"


def _derive_accession_number(filename: str) -> str | None:
    match = _ACCESSION_RE.search(filename)
    if not match:
        return None
    return match.group(1)


def _require_columns(df: pd.DataFrame, required: set[str], context: str) -> None:
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(
            f"{context} is missing required columns: {', '.join(missing)}. "
            "Run `py-sec-edgar index refresh` to regenerate merged index data."
        )


def _list_files(path: Path) -> list[str]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(str(item) for item in path.rglob("*") if item.is_file())


def _load_filing_party_counts(config: AppConfig) -> tuple[bool, dict[str, int]]:
    filing_parties_path = config.normalized_refdata_root / "filing_parties.parquet"
    if not filing_parties_path.exists():
        return False, {}

    df = pd.read_parquet(filing_parties_path)
    if "accession_number" not in df.columns or df.empty:
        return True, {}
    counts = (
        df["accession_number"]
        .astype(str)
        .value_counts(dropna=False)
        .to_dict()
    )
    return True, {str(k): int(v) for k, v in counts.items()}


def _build_extracted_dir_file_map(merged: pd.DataFrame, download_root: Path) -> dict[str, list[str]]:
    extracted_dirs: set[str] = set()
    for filename in merged["Filename"].astype(str).tolist():
        normalized = str(filename).strip()
        if not normalized:
            continue
        relative = normalized.lstrip("/")
        submission_path = download_root / Path(relative)
        extracted_dir = submission_path.parent / submission_path.stem.replace("-", "")
        extracted_dirs.add(str(extracted_dir))
    return {directory: _list_files(Path(directory)) for directory in sorted(extracted_dirs)}


def _load_merged_index_df(config: AppConfig) -> pd.DataFrame:
    merged_path = config.merged_index_path
    if not merged_path.exists():
        raise FileNotFoundError(f"Merged index file not found: {merged_path}. Run `py-sec-edgar index refresh` first.")
    merged = pd.read_parquet(merged_path)
    _require_columns(merged, _MERGED_IDX_REQUIRED_COLUMNS, "Merged index dataset")
    return merged


def _build_filing_placements_from_merged(
    config: AppConfig,
    merged: pd.DataFrame,
) -> tuple[pd.DataFrame, bool, int]:
    extracted_dir_file_map = _build_extracted_dir_file_map(merged, config.download_root)

    filing_parties_available, filing_party_counts = _load_filing_party_counts(config)

    rows: list[dict[str, object]] = []
    for row in merged.to_dict(orient="records"):
        filename = str(row.get("Filename") or "").strip()
        if not filename:
            continue
        relative = filename.lstrip("/")
        submission_path = config.download_root / Path(relative)
        extracted_dir = submission_path.parent / submission_path.stem.replace("-", "")
        extracted_files = extracted_dir_file_map.get(str(extracted_dir), [])
        extracted_file_count = len(extracted_files)
        accession_number = _derive_accession_number(filename)
        filing_party_count = int(filing_party_counts.get(str(accession_number), 0)) if accession_number else 0

        rows.append(
            {
                "accession_number": accession_number,
                "filing_cik": normalize_cik(row.get("CIK")),
                "form_type": str(row.get("Form Type") or "").strip().upper(),
                "filing_date": str(row.get("Date Filed") or "").strip(),
                "filename": filename,
                "submission_path": str(submission_path),
                "submission_exists": bool(submission_path.exists()),
                "extracted_dir_path": str(extracted_dir),
                "extracted_file_count": int(extracted_file_count),
                "has_extracted_artifacts": bool(extracted_file_count > 0),
                "filing_party_record_count": int(filing_party_count),
                "has_filing_parties": bool(filing_party_count > 0),
                "_dedupe_key": accession_number or filename,
                "_extracted_files": extracted_files,
            }
        )

    placements_df = pd.DataFrame(
        rows,
        columns=[
            "accession_number",
            "filing_cik",
            "form_type",
            "filing_date",
            "filename",
            "submission_path",
            "submission_exists",
            "extracted_dir_path",
            "extracted_file_count",
            "has_extracted_artifacts",
            "filing_party_record_count",
            "has_filing_parties",
            "_dedupe_key",
            "_extracted_files",
        ],
    )
    if not placements_df.empty:
        placements_df = placements_df.sort_values(
            ["filing_date", "form_type", "filing_cik", "filename"],
            ascending=[False, True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    return placements_df, filing_parties_available, int(len(extracted_dir_file_map))


def _build_filing_placements(
    config: AppConfig,
) -> tuple[pd.DataFrame, bool, int]:
    merged = _load_merged_index_df(config)
    return _build_filing_placements_from_merged(config, merged)


def _build_artifacts_lookup(placements_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for row in placements_df.to_dict(orient="records"):
        accession_number = row.get("accession_number")
        filing_cik = row.get("filing_cik")
        form_type = row.get("form_type")
        filing_date = row.get("filing_date")
        source_filename = row.get("filename")
        submission_path = Path(str(row.get("submission_path")))

        if bool(row.get("submission_exists")):
            rows.append(
                {
                    "accession_number": accession_number,
                    "filing_cik": filing_cik,
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "artifact_type": "submission",
                    "artifact_path": str(submission_path),
                    "artifact_name": submission_path.name,
                    "source_filename": source_filename,
                }
            )

        for extracted_file in row.get("_extracted_files") or []:
            rows.append(
                {
                    "accession_number": accession_number,
                    "filing_cik": filing_cik,
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "artifact_type": "extracted",
                    "artifact_path": str(extracted_file),
                    "artifact_name": Path(str(extracted_file)).name,
                    "source_filename": source_filename,
                }
            )

    artifacts_df = pd.DataFrame(
        rows,
        columns=[
            "accession_number",
            "filing_cik",
            "form_type",
            "filing_date",
            "artifact_type",
            "artifact_path",
            "artifact_name",
            "source_filename",
        ],
    )
    if not artifacts_df.empty:
        artifacts_df = artifacts_df.sort_values(
            ["accession_number", "artifact_type", "artifact_path"],
            ascending=[True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    return artifacts_df


def _empty_filings_df() -> pd.DataFrame:
    return _dedupe_filings(pd.DataFrame())


def _empty_artifacts_df() -> pd.DataFrame:
    return _build_artifacts_lookup(pd.DataFrame())


def _normalize_filename(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.lstrip("/")


def _normalize_accession(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _load_lookup_or_empty(path: Path, empty_df_factory) -> pd.DataFrame:
    if not path.exists():
        return empty_df_factory()
    df = pd.read_parquet(path)
    expected_cols = list(empty_df_factory().columns)
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None
    return df[expected_cols]


def _sort_filings_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["filing_date", "form_type", "filing_cik", "filename"],
        ascending=[False, True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _sort_artifacts_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["accession_number", "artifact_type", "artifact_path"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _dedupe_filings(placements_df: pd.DataFrame) -> pd.DataFrame:
    if placements_df.empty:
        return pd.DataFrame(
            columns=[
                "accession_number",
                "filing_cik",
                "form_type",
                "filing_date",
                "filename",
                "submission_path",
                "submission_exists",
                "local_submission_path_count",
                "submission_path_count",
                "extracted_dir_path",
                "local_extracted_dir_count",
                "local_artifact_file_count",
                "extracted_file_count",
                "has_extracted_artifacts",
                "filing_party_record_count_max",
                "filing_party_record_count",
                "has_filing_parties",
            ]
        )

    out_rows: list[dict[str, object]] = []
    for _, group in placements_df.groupby("_dedupe_key", dropna=False, sort=True):
        # Deterministic representative row contract:
        # choose canonical row by lexicographically smallest submission_path.
        canonical = group.sort_values("submission_path", ascending=True, na_position="last").iloc[0]
        local_submission_paths = {
            str(path)
            for path, exists in zip(group["submission_path"], group["submission_exists"])
            if bool(exists)
        }
        local_extracted_dirs: set[str] = set()
        local_artifact_files: set[str] = set()
        for extracted_dir, files in zip(group["extracted_dir_path"], group["_extracted_files"]):
            normalized_files = [str(item) for item in (files or [])]
            if normalized_files:
                local_extracted_dirs.add(str(extracted_dir))
                local_artifact_files.update(normalized_files)
        max_filing_party_count = int(group["filing_party_record_count"].fillna(0).astype(int).max())

        out_rows.append(
            {
                "accession_number": canonical["accession_number"],
                "filing_cik": canonical["filing_cik"],
                "form_type": canonical["form_type"],
                "filing_date": canonical["filing_date"],
                "filename": canonical["filename"],
                "submission_path": canonical["submission_path"],
                "submission_exists": bool(group["submission_exists"].any()),
                "local_submission_path_count": int(len(local_submission_paths)),
                # Backward-compatible alias retained for existing query/tests.
                "submission_path_count": int(len(local_submission_paths)),
                "extracted_dir_path": canonical["extracted_dir_path"],
                "local_extracted_dir_count": int(len(local_extracted_dirs)),
                "local_artifact_file_count": int(len(local_artifact_files)),
                # Backward-compatible alias retained for existing query/tests.
                "extracted_file_count": int(len(local_artifact_files)),
                "has_extracted_artifacts": bool(len(local_artifact_files) > 0),
                "filing_party_record_count_max": int(max_filing_party_count),
                # Backward-compatible alias retained for existing query/tests.
                "filing_party_record_count": int(max_filing_party_count),
                "has_filing_parties": bool(max_filing_party_count > 0),
            }
        )

    out = pd.DataFrame(out_rows)
    return out.sort_values(
        ["filing_date", "form_type", "filing_cik", "filename"],
        ascending=[False, True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _filter_local_presence(placements_df: pd.DataFrame) -> pd.DataFrame:
    if placements_df.empty:
        return placements_df.copy()
    mask = (
        placements_df["submission_exists"].astype(bool)
        | (placements_df["extracted_file_count"].fillna(0).astype(int) > 0)
        | (placements_df["filing_party_record_count"].fillna(0).astype(int) > 0)
    )
    return placements_df[mask].reset_index(drop=True)


def _emit_lookup_progress(
    callback: Callable[[dict[str, object]], None] | None,
    *,
    phase: str,
    counters: dict[str, object],
    detail: str | None = None,
) -> None:
    if callback is None:
        return
    payload: dict[str, object] = {
        "phase": str(phase),
        "counters": {str(k): v for k, v in counters.items()},
    }
    if detail:
        payload["detail"] = str(detail)
    callback(payload)


def refresh_local_lookup_indexes(
    config: AppConfig,
    *,
    include_global_filings: bool = False,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    started_at = time.monotonic()
    config.ensure_runtime_dirs()

    progress_counters: dict[str, object] = {
        "placement_row_count": 0,
        "local_placement_row_count": 0,
        "scanned_extracted_dir_count": 0,
        "deduped_local_filing_row_count": 0,
        "filings_row_count": 0,
        "artifacts_row_count": 0,
    }
    _emit_lookup_progress(progress_callback, phase="lookup.refresh.start", counters=progress_counters, detail="started")

    _emit_lookup_progress(progress_callback, phase="lookup.refresh.load_merged_index", counters=progress_counters)
    merged = _load_merged_index_df(config)

    _emit_lookup_progress(progress_callback, phase="lookup.refresh.scan_extracted_dirs", counters=progress_counters)
    placements_df, filing_parties_available, scanned_extracted_dir_count = _build_filing_placements_from_merged(config, merged)
    progress_counters["placement_row_count"] = int(len(placements_df.index))
    progress_counters["scanned_extracted_dir_count"] = int(scanned_extracted_dir_count)
    _emit_lookup_progress(progress_callback, phase="lookup.refresh.build_placements", counters=progress_counters)

    local_placements_df = _filter_local_presence(placements_df)
    progress_counters["local_placement_row_count"] = int(len(local_placements_df.index))
    _emit_lookup_progress(progress_callback, phase="lookup.refresh.filter_local_presence", counters=progress_counters)

    local_filings_df = _dedupe_filings(local_placements_df)
    progress_counters["deduped_local_filing_row_count"] = int(len(local_filings_df.index))
    progress_counters["filings_row_count"] = int(len(local_filings_df.index))
    _emit_lookup_progress(progress_callback, phase="lookup.refresh.dedupe_filings", counters=progress_counters)

    artifacts_df = _build_artifacts_lookup(local_placements_df)
    progress_counters["artifacts_row_count"] = int(len(artifacts_df.index))
    _emit_lookup_progress(progress_callback, phase="lookup.refresh.build_artifacts", counters=progress_counters)

    global_filings_df = _dedupe_filings(placements_df) if include_global_filings else None

    filings_path = local_lookup_filings_path(config)
    artifacts_path = local_lookup_artifacts_path(config)
    filings_all_path = local_lookup_filings_all_path(config)

    _emit_lookup_progress(progress_callback, phase="lookup.refresh.write_outputs", counters=progress_counters)
    local_filings_df.to_parquet(filings_path, index=False)
    artifacts_df.to_parquet(artifacts_path, index=False)
    if global_filings_df is not None:
        global_filings_df.to_parquet(filings_all_path, index=False)

    _emit_lookup_progress(progress_callback, phase="lookup.refresh.complete", counters=progress_counters, detail="completed")

    return {
        "filings_index_path": str(filings_path),
        "artifacts_index_path": str(artifacts_path),
        "placement_row_count": int(len(placements_df.index)),
        "local_placement_row_count": int(len(local_placements_df.index)),
        "deduped_local_filing_row_count": int(len(local_filings_df.index)),
        "deduped_global_filing_row_count": int(len(global_filings_df.index)) if global_filings_df is not None else 0,
        "scanned_extracted_dir_count": int(scanned_extracted_dir_count),
        "filings_row_count": int(len(local_filings_df.index)),
        "artifacts_row_count": int(len(artifacts_df.index)),
        "global_filings_index_path": str(filings_all_path) if global_filings_df is not None else None,
        "global_filings_index_written": bool(global_filings_df is not None),
        "global_filings_row_count": int(len(global_filings_df.index)) if global_filings_df is not None else 0,
        "filing_parties_available": bool(filing_parties_available),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def register_local_filings_in_lookup(
    config: AppConfig,
    *,
    warmed_filenames: list[str] | None = None,
    warmed_accession_numbers: list[str] | None = None,
) -> dict[str, object]:
    started_at = time.monotonic()
    config.ensure_runtime_dirs()

    requested_filenames = {name for name in (_normalize_filename(v) for v in (warmed_filenames or [])) if name}
    requested_accessions = {acc for acc in (_normalize_accession(v) for v in (warmed_accession_numbers or [])) if acc}
    attempted_input_count = int(len(requested_filenames) + len(requested_accessions))

    filings_path = local_lookup_filings_path(config)
    artifacts_path = local_lookup_artifacts_path(config)

    skip_reasons: dict[str, int] = {}
    safe_to_use = True

    if attempted_input_count == 0:
        safe_to_use = False
        skip_reasons["no_warmed_inputs"] = 1
        local_filings_df = _load_lookup_or_empty(filings_path, _empty_filings_df)
        local_artifacts_df = _load_lookup_or_empty(artifacts_path, _empty_artifacts_df)
        local_filings_df.to_parquet(filings_path, index=False)
        local_artifacts_df.to_parquet(artifacts_path, index=False)
        return {
            "attempted_input_count": attempted_input_count,
            "matched_merged_rows_count": 0,
            "registered_filing_row_count": 0,
            "registered_artifact_row_count": 0,
            "skipped_count": int(sum(skip_reasons.values())),
            "skip_reasons": skip_reasons,
            "safe_to_use": bool(safe_to_use),
            "touched_accession_count": 0,
            "touched_filename_count": 0,
            "filings_index_path": str(filings_path),
            "artifacts_index_path": str(artifacts_path),
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
        }

    merged = _load_merged_index_df(config)
    rows = merged.to_dict(orient="records")

    matched_rows: list[dict[str, object]] = []
    matched_filenames: set[str] = set()
    matched_accessions: set[str] = set()
    for row in rows:
        filename = _normalize_filename(row.get("Filename"))
        if filename is None:
            continue
        accession = _derive_accession_number(filename)
        by_filename = filename in requested_filenames
        by_accession = accession in requested_accessions if accession else False
        if not (by_filename or by_accession):
            continue
        matched_rows.append(row)
        matched_filenames.add(filename)
        if accession:
            matched_accessions.add(accession)

    unmatched_filenames = requested_filenames.difference(matched_filenames)
    unmatched_accessions = requested_accessions.difference(matched_accessions)
    if unmatched_filenames:
        safe_to_use = False
        skip_reasons["filename_not_found_in_merged_index"] = len(unmatched_filenames)
    if unmatched_accessions:
        safe_to_use = False
        skip_reasons["accession_not_found_in_merged_index"] = len(unmatched_accessions)

    if not matched_rows:
        safe_to_use = False
        skip_reasons["no_merged_index_matches"] = skip_reasons.get("no_merged_index_matches", 0) + 1
        local_filings_df = _load_lookup_or_empty(filings_path, _empty_filings_df)
        local_artifacts_df = _load_lookup_or_empty(artifacts_path, _empty_artifacts_df)
        local_filings_df.to_parquet(filings_path, index=False)
        local_artifacts_df.to_parquet(artifacts_path, index=False)
        return {
            "attempted_input_count": attempted_input_count,
            "matched_merged_rows_count": 0,
            "registered_filing_row_count": 0,
            "registered_artifact_row_count": 0,
            "skipped_count": int(sum(skip_reasons.values())),
            "skip_reasons": skip_reasons,
            "safe_to_use": bool(safe_to_use),
            "touched_accession_count": int(len(matched_accessions)),
            "touched_filename_count": int(len(matched_filenames)),
            "filings_index_path": str(filings_path),
            "artifacts_index_path": str(artifacts_path),
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
        }

    subset = pd.DataFrame(matched_rows)
    placements_df, _, _ = _build_filing_placements_from_merged(config, subset)
    local_placements_df = _filter_local_presence(placements_df)
    new_filings_df = _dedupe_filings(local_placements_df)
    new_artifacts_df = _build_artifacts_lookup(local_placements_df)

    if placements_df.empty:
        safe_to_use = False
        skip_reasons["empty_placement_rows"] = skip_reasons.get("empty_placement_rows", 0) + 1
    if local_placements_df.empty:
        safe_to_use = False
        skip_reasons["no_local_presence_for_matches"] = skip_reasons.get("no_local_presence_for_matches", 0) + 1

    touched_filenames = {name for name in (_normalize_filename(v) for v in placements_df.get("filename", pd.Series()).tolist()) if name}
    touched_accessions = {acc for acc in (_normalize_accession(v) for v in placements_df.get("accession_number", pd.Series()).tolist()) if acc}

    existing_filings_df = _load_lookup_or_empty(filings_path, _empty_filings_df)
    if not existing_filings_df.empty and (touched_filenames or touched_accessions):
        existing_filings_accessions = existing_filings_df["accession_number"].map(_normalize_accession)
        existing_filings_filenames = existing_filings_df["filename"].map(_normalize_filename)
        accession_present = existing_filings_accessions.notna()
        remove_by_accession = accession_present & existing_filings_accessions.isin(touched_accessions)
        remove_by_filename = (~accession_present) & existing_filings_filenames.isin(touched_filenames)
        existing_filings_df = existing_filings_df[~(remove_by_accession | remove_by_filename)].reset_index(drop=True)

    merged_filings_df = pd.concat([existing_filings_df, new_filings_df], ignore_index=True)
    merged_filings_df = _sort_filings_df(merged_filings_df)
    merged_filings_df.to_parquet(filings_path, index=False)

    existing_artifacts_df = _load_lookup_or_empty(artifacts_path, _empty_artifacts_df)
    if not existing_artifacts_df.empty and (touched_filenames or touched_accessions):
        existing_artifacts_accessions = existing_artifacts_df["accession_number"].map(_normalize_accession)
        existing_artifacts_filenames = existing_artifacts_df["source_filename"].map(_normalize_filename)
        remove_artifacts = existing_artifacts_accessions.isin(touched_accessions) | existing_artifacts_filenames.isin(touched_filenames)
        existing_artifacts_df = existing_artifacts_df[~remove_artifacts].reset_index(drop=True)

    merged_artifacts_df = pd.concat([existing_artifacts_df, new_artifacts_df], ignore_index=True)
    merged_artifacts_df = _sort_artifacts_df(merged_artifacts_df)
    merged_artifacts_df.to_parquet(artifacts_path, index=False)

    return {
        "attempted_input_count": attempted_input_count,
        "matched_merged_rows_count": int(len(matched_rows)),
        "registered_filing_row_count": int(len(new_filings_df.index)),
        "registered_artifact_row_count": int(len(new_artifacts_df.index)),
        "skipped_count": int(sum(skip_reasons.values())),
        "skip_reasons": skip_reasons,
        "safe_to_use": bool(safe_to_use),
        "touched_accession_count": int(len(touched_accessions)),
        "touched_filename_count": int(len(touched_filenames)),
        "filings_index_path": str(filings_path),
        "artifacts_index_path": str(artifacts_path),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def load_lookup_dataframe(
    config: AppConfig,
    scope: str,
    *,
    use_global_filings: bool = False,
) -> pd.DataFrame:
    if scope == "filings":
        path = local_lookup_filings_all_path(config) if use_global_filings else local_lookup_filings_path(config)
    else:
        path = local_lookup_artifacts_path(config)

    if not path.exists():
        if scope == "filings" and use_global_filings:
            raise FileNotFoundError(
                f"Missing lookup artifact: {path}. "
                "Run `py-sec-edgar lookup refresh --include-global-filings`."
            )
        raise FileNotFoundError(f"Missing lookup artifact: {path}. Run `py-sec-edgar lookup refresh`.")
    return pd.read_parquet(path)


def query_lookup(
    df: pd.DataFrame,
    *,
    scope: str,
    accession_numbers: list[str] | None = None,
    ciks: list[str] | None = None,
    form_types: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    artifact_types: list[str] | None = None,
    path_contains: str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    accession_set = {str(item).strip() for item in (accession_numbers or []) if str(item).strip()}
    cik_set = {normalize_cik(item) for item in (ciks or []) if normalize_cik(item)}
    form_set = {str(item).strip().upper() for item in (form_types or []) if str(item).strip()}
    artifact_type_set = {str(item).strip().lower() for item in (artifact_types or []) if str(item).strip()}

    if accession_set and "accession_number" in out.columns:
        out = out[out["accession_number"].astype(str).isin(accession_set)]
    if cik_set and "filing_cik" in out.columns:
        out["filing_cik"] = out["filing_cik"].map(normalize_cik)
        out = out[out["filing_cik"].isin(cik_set)]
    if form_set and "form_type" in out.columns:
        out = out[out["form_type"].astype(str).str.upper().isin(form_set)]
    if artifact_type_set and scope == "artifacts" and "artifact_type" in out.columns:
        out = out[out["artifact_type"].astype(str).str.lower().isin(artifact_type_set)]
    if path_contains and scope == "artifacts" and "artifact_path" in out.columns:
        needle = str(path_contains).strip().lower()
        out = out[out["artifact_path"].astype(str).str.lower().str.contains(needle, regex=False)]

    if (date_from is not None or date_to is not None) and "filing_date" in out.columns:
        filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
        if date_from is not None:
            out = out[filing_dates >= pd.to_datetime(date_from)]
            filing_dates = pd.to_datetime(out["filing_date"], errors="coerce")
        if date_to is not None:
            out = out[filing_dates <= pd.to_datetime(date_to)]

    if scope == "filings":
        sort_cols = [c for c in ["filing_date", "form_type", "filing_cik", "filename"] if c in out.columns]
        ascending = [False, True, True, True][: len(sort_cols)]
    else:
        sort_cols = [c for c in ["accession_number", "artifact_type", "artifact_path"] if c in out.columns]
        ascending = [True] * len(sort_cols)
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=ascending, na_position="last")
    return out.reset_index(drop=True)


def parse_columns_option(columns_csv: str | None) -> list[str] | None:
    if columns_csv is None:
        return None
    requested = [item.strip() for item in columns_csv.split(",") if item.strip()]
    return requested or None


def apply_limit_and_columns(
    df: pd.DataFrame,
    *,
    limit: int | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    out = df.copy()
    if limit is not None:
        out = out.head(int(limit))

    if columns is not None:
        missing = [name for name in columns if name not in out.columns]
        if missing:
            raise ValueError(f"Unknown column(s): {', '.join(missing)}")
        out = out[columns]
    return out
