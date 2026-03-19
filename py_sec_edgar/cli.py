from __future__ import annotations

import json
from pathlib import Path

import click
from click.core import ParameterSource

from py_sec_edgar.config import load_config
from py_sec_edgar.filters import FORM_FAMILY_MAP
from py_sec_edgar.filing_parties_query import (
    apply_limit_and_columns,
    load_filing_parties_parquet,
    parse_columns_option,
    query_filing_parties,
)
from py_sec_edgar.logging_utils import configure_logging
from py_sec_edgar.lookup import (
    apply_limit_and_columns as apply_lookup_limit_and_columns,
    load_lookup_dataframe,
    parse_columns_option as parse_lookup_columns_option,
    query_lookup,
    refresh_local_lookup_indexes,
)
from py_sec_edgar.pipelines.backfill import run_backfill
from py_sec_edgar.pipelines.index_refresh import run_index_refresh
from py_sec_edgar.pipelines.refdata_refresh import run_refdata_refresh
from py_sec_edgar.runtime_output import (
    DEFAULT_ACTIVITY_WINDOW,
    bounded_recent_activity,
    render_activity_block,
    render_summary_block,
)


@click.group()
def main() -> None:
    """py-sec-edgar command line interface."""


@main.group("refdata")
def refdata_group() -> None:
    """Reference-data operations."""


@refdata_group.command("refresh")
@click.option(
    "--project-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Project root containing refdata/sec_sources.",
)
@click.option("--verbose/--no-verbose", default=False, show_default=True, help="Show bounded recent activity output on stderr.")
@click.option("--quiet/--no-quiet", default=False, show_default=True, help="Suppress non-essential human-readable output.")
@click.option(
    "--log-level",
    type=click.Choice(["ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Console log level.",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True),
    default=None,
    help="Optional log file path.",
)
def refdata_refresh(
    project_root: Path | None,
    verbose: bool,
    quiet: bool,
    log_level: str,
    log_file: Path | None,
) -> None:
    config = load_config(project_root)
    configure_logging(log_level=log_level, log_file=str(log_file) if log_file else None)
    try:
        result = run_refdata_refresh(config) or {}
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    written = result.get("written", {})

    if quiet:
        click.echo("Refdata refresh complete.")
        return

    summary = render_summary_block(
        "Refdata refresh complete.",
        {
            "artifact_count": result.get("artifact_count", len(written)),
            "artifact_paths": ", ".join(result.get("artifact_paths", [])),
            "elapsed_seconds": result.get("elapsed_seconds", 0.0),
        },
    )
    click.echo(summary)
    if verbose:
        click.echo(
            render_activity_block(result.get("activity_events", []), window=DEFAULT_ACTIVITY_WINDOW),
            err=True,
        )


@main.group("index")
def index_group() -> None:
    """EDGAR index operations."""


@index_group.command("refresh")
@click.option(
    "--skip-if-exists/--no-skip-if-exists",
    default=True,
    show_default=True,
    help="Skip re-downloading files already present.",
)
@click.option(
    "--save-idx-as-csv/--no-save-idx-as-csv",
    default=True,
    show_default=True,
    help="Convert downloaded .idx files to .csv.",
)
@click.option("--verbose/--no-verbose", default=False, show_default=True, help="Show bounded recent activity output on stderr.")
@click.option("--quiet/--no-quiet", default=False, show_default=True, help="Suppress non-essential human-readable output.")
@click.option(
    "--log-level",
    type=click.Choice(["ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Console log level.",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True),
    default=None,
    help="Optional log file path.",
)
def index_refresh(
    skip_if_exists: bool,
    save_idx_as_csv: bool,
    verbose: bool,
    quiet: bool,
    log_level: str,
    log_file: Path | None,
) -> None:
    config = load_config()
    configure_logging(log_level=log_level, log_file=str(log_file) if log_file else None)
    result = run_index_refresh(
        config,
        save_idx_as_csv=save_idx_as_csv,
        skip_if_exists=skip_if_exists,
    ) or {}
    if not quiet:
        summary = render_summary_block(
            "Index refresh complete.",
            {
                "download_attempted_count": result.get("download_attempted_count", 0),
                "download_succeeded_count": result.get("download_succeeded_count", 0),
                "download_failed_count": result.get("download_failed_count", 0),
                "converted_count": result.get("converted_count", 0),
                "merge_completed": result.get("merge_completed", False),
                "total_elapsed_seconds": result.get("total_elapsed_seconds", 0.0),
            },
        )
        click.echo(summary)
    if verbose and not quiet:
        click.echo(
            render_activity_block(result.get("activity_events", []), window=DEFAULT_ACTIVITY_WINDOW),
            err=True,
        )


@main.group("filing-parties")
def filing_parties_group() -> None:
    """Filing-party data query operations."""


@filing_parties_group.command("query")
@click.option("--issuer-cik", "issuer_ciks", multiple=True, help="Filter by issuer CIK. Repeat for multiple values.")
@click.option("--party-cik", "party_ciks", multiple=True, help="Filter by party CIK. Repeat for multiple values.")
@click.option("--role", "roles", multiple=True, help="Filter by party role. Repeat for multiple values.")
@click.option("--form-type", "form_types", multiple=True, help="Filter by form type. Repeat for multiple values.")
@click.option("--accession-number", "accession_numbers", multiple=True, help="Filter by accession number. Repeat for multiple values.")
@click.option("--date-from", default=None, help="Lower filing date bound (inclusive), e.g. 2025-01-01.")
@click.option("--date-to", default=None, help="Upper filing date bound (inclusive), e.g. 2025-03-31.")
@click.option("--limit", type=click.IntRange(min=0), default=None, help="Limit result rows after filtering/sorting.")
@click.option("--columns", default=None, help="Comma-separated output columns (e.g. accession_number,party_name,party_role).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON records only.")
def filing_parties_query(
    issuer_ciks: tuple[str, ...],
    party_ciks: tuple[str, ...],
    roles: tuple[str, ...],
    form_types: tuple[str, ...],
    accession_numbers: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    limit: int | None,
    columns: str | None,
    as_json: bool,
) -> None:
    config = load_config()
    try:
        df = load_filing_parties_parquet(config)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    filtered = query_filing_parties(
        df,
        issuer_ciks=list(issuer_ciks) or None,
        party_ciks=list(party_ciks) or None,
        roles=list(roles) or None,
        form_types=list(form_types) or None,
        accession_numbers=list(accession_numbers) or None,
        date_from=date_from,
        date_to=date_to,
    )
    selected_columns = parse_columns_option(columns)
    try:
        filtered = apply_limit_and_columns(filtered, limit=limit, columns=selected_columns)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(filtered.to_dict(orient="records"), sort_keys=True))
        return

    if filtered.empty:
        click.echo("No filing-party rows matched.")
        return

    if selected_columns is None:
        cols = [
            c
            for c in [
                "accession_number",
                "form_type",
                "filing_date",
                "party_role",
                "party_cik",
                "party_name",
                "issuer_cik",
                "issuer_name",
                "source_filename",
            ]
            if c in filtered.columns
        ]
        click.echo(filtered[cols].to_string(index=False))
        return

    click.echo(filtered.to_string(index=False))


@main.group("lookup")
def lookup_group() -> None:
    """Local lookup index operations."""


@lookup_group.command("refresh")
@click.option(
    "--include-global-filings/--no-include-global-filings",
    default=False,
    show_default=True,
    help="Also build a merged-index-wide filings lookup artifact.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON summary instead of human-readable lines.",
)
def lookup_refresh(
    include_global_filings: bool,
    summary_json: bool,
) -> None:
    config = load_config()
    try:
        result = refresh_local_lookup_indexes(config, include_global_filings=include_global_filings)
    except FileNotFoundError as exc:
        message = str(exc)
        if "Merged index file not found:" in message:
            raise click.ClickException(f"{message} Run `py-sec-edgar index refresh` first.") from exc
        raise click.ClickException(message) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if summary_json:
        click.echo(json.dumps(result, sort_keys=True))
        return

    summary = render_summary_block(
        "Lookup refresh complete.",
        {
            "filings_index_path": result.get("filings_index_path"),
            "artifacts_index_path": result.get("artifacts_index_path"),
            "placement_row_count": result.get("placement_row_count"),
            "local_placement_row_count": result.get("local_placement_row_count"),
            "deduped_local_filing_row_count": result.get("deduped_local_filing_row_count"),
            "deduped_global_filing_row_count": result.get("deduped_global_filing_row_count"),
            "scanned_extracted_dir_count": result.get("scanned_extracted_dir_count"),
            "filings_row_count": result.get("filings_row_count"),
            "artifacts_row_count": result.get("artifacts_row_count"),
            "global_filings_index_written": result.get("global_filings_index_written"),
            "global_filings_row_count": result.get("global_filings_row_count"),
            "filing_parties_available": result.get("filing_parties_available"),
            "elapsed_seconds": result.get("elapsed_seconds"),
        },
    )
    click.echo(summary)


@lookup_group.command("query")
@click.option(
    "--scope",
    type=click.Choice(["filings", "artifacts"], case_sensitive=False),
    default="filings",
    show_default=True,
    help="Lookup scope.",
)
@click.option("--accession-number", "accession_numbers", multiple=True, help="Filter by accession number. Repeat for multiple values.")
@click.option("--cik", "ciks", multiple=True, help="Filter by CIK. Repeat for multiple values.")
@click.option("--form-type", "form_types", multiple=True, help="Filter by form type. Repeat for multiple values.")
@click.option("--date-from", default=None, help="Lower filing date bound (inclusive), e.g. 2025-01-01.")
@click.option("--date-to", default=None, help="Upper filing date bound (inclusive), e.g. 2025-03-31.")
@click.option("--artifact-type", "artifact_types", multiple=True, help="Filter artifact rows by type (submission or extracted).")
@click.option("--path-contains", default=None, help="Case-insensitive substring filter for artifact_path (artifacts scope only).")
@click.option("--all", "all_filings", is_flag=True, default=False, help="Use merged-index-wide filings lookup (requires refresh with --include-global-filings).")
@click.option("--limit", type=click.IntRange(min=0), default=None, help="Limit result rows after filtering/sorting.")
@click.option("--columns", default=None, help="Comma-separated output columns.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON records only.")
def lookup_query(
    scope: str,
    accession_numbers: tuple[str, ...],
    ciks: tuple[str, ...],
    form_types: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    artifact_types: tuple[str, ...],
    path_contains: str | None,
    all_filings: bool,
    limit: int | None,
    columns: str | None,
    as_json: bool,
) -> None:
    if scope.lower() == "artifacts" and all_filings:
        raise click.ClickException("`--all` is only supported for `--scope filings`.")
    config = load_config()
    try:
        df = load_lookup_dataframe(config, scope=scope.lower(), use_global_filings=all_filings)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    filtered = query_lookup(
        df,
        scope=scope.lower(),
        accession_numbers=list(accession_numbers) or None,
        ciks=list(ciks) or None,
        form_types=list(form_types) or None,
        date_from=date_from,
        date_to=date_to,
        artifact_types=list(artifact_types) or None,
        path_contains=path_contains,
    )
    selected_columns = parse_lookup_columns_option(columns)
    try:
        filtered = apply_lookup_limit_and_columns(filtered, limit=limit, columns=selected_columns)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(filtered.to_dict(orient="records"), sort_keys=True))
        return

    if filtered.empty:
        click.echo("No lookup rows matched.")
        return

    if selected_columns is None:
        if scope.lower() == "filings":
            cols = [
                c
                for c in [
                    "accession_number",
                    "filing_cik",
                    "form_type",
                    "filing_date",
                    "submission_exists",
                    "local_submission_path_count",
                    "local_extracted_dir_count",
                    "has_extracted_artifacts",
                    "local_artifact_file_count",
                    "filing_party_record_count_max",
                    "has_filing_parties",
                    "filename",
                ]
                if c in filtered.columns
            ]
        else:
            cols = [
                c
                for c in [
                    "accession_number",
                    "filing_cik",
                    "form_type",
                    "filing_date",
                    "artifact_type",
                    "artifact_path",
                ]
                if c in filtered.columns
            ]
        click.echo(filtered[cols].to_string(index=False))
        return

    click.echo(filtered.to_string(index=False))


@main.command("backfill")
@click.pass_context
@click.option(
    "--refresh-index/--no-refresh-index",
    default=True,
    show_default=True,
    help="Refresh index files before candidate loading.",
)
@click.option(
    "--execute-downloads/--no-execute-downloads",
    default=False,
    show_default=True,
    help="Execute filing downloads for selected candidates after filtering.",
)
@click.option(
    "--execute-extraction/--no-execute-extraction",
    default=False,
    show_default=True,
    help="Execute serial extraction for selected filings using local downloaded files.",
)
@click.option(
    "--persist-filing-parties/--no-persist-filing-parties",
    default=False,
    show_default=True,
    help="Persist extracted filing-party records to refdata/normalized/filing_parties.parquet.",
)
@click.option(
    "--ticker-list-filter/--no-ticker-list-filter",
    default=True,
    show_default=True,
    help="Use legacy ticker list filtering from settings.",
)
@click.option(
    "--form-list-filter/--no-form-list-filter",
    default=True,
    show_default=True,
    help="Use legacy form list filtering from settings.",
)
@click.option(
    "--issuer-ticker",
    "issuer_tickers",
    multiple=True,
    help="Issuer ticker filter. Repeat for multiple values.",
)
@click.option(
    "--issuer-cik",
    "issuer_ciks",
    multiple=True,
    help="Issuer CIK filter (any format; canonicalized internally). Repeat for multiple values.",
)
@click.option(
    "--entity-cik",
    "entity_ciks",
    multiple=True,
    help="Entity CIK filter (any format; canonicalized internally). Repeat for multiple values.",
)
@click.option(
    "--form",
    "forms",
    multiple=True,
    help="Form filter. Repeat for multiple values.",
)
@click.option(
    "--form-family",
    "form_families",
    type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False),
    multiple=True,
    help="Form family filter. Repeat for multiple values.",
)
@click.option(
    "--date-from",
    default=None,
    help="Lower filing date bound (inclusive), e.g. 2025-01-01.",
)
@click.option(
    "--date-to",
    default=None,
    help="Upper filing date bound (inclusive), e.g. 2025-03-31.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON summary instead of human-readable lines.",
)
@click.option("--verbose/--no-verbose", default=False, show_default=True, help="Show bounded recent activity output on stderr.")
@click.option("--quiet/--no-quiet", default=False, show_default=True, help="Suppress non-essential human-readable output.")
@click.option(
    "--log-level",
    type=click.Choice(["ERROR", "WARNING", "INFO", "DEBUG"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Console log level.",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True),
    default=None,
    help="Optional log file path.",
)
def backfill(
    ctx: click.Context,
    refresh_index: bool,
    execute_downloads: bool,
    execute_extraction: bool,
    persist_filing_parties: bool,
    ticker_list_filter: bool,
    form_list_filter: bool,
    issuer_tickers: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    entity_ciks: tuple[str, ...],
    forms: tuple[str, ...],
    form_families: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    summary_json: bool,
    verbose: bool,
    quiet: bool,
    log_level: str,
    log_file: Path | None,
) -> None:
    config = load_config()
    configure_logging(log_level=log_level, log_file=str(log_file) if log_file else None)
    ticker_list_filter_explicit = (
        ctx.get_parameter_source("ticker_list_filter") != ParameterSource.DEFAULT
    )
    form_list_filter_explicit = (
        ctx.get_parameter_source("form_list_filter") != ParameterSource.DEFAULT
    )
    try:
        result = run_backfill(
            config,
            refresh_index=refresh_index,
            execute_downloads=execute_downloads,
            execute_extraction=execute_extraction,
            persist_filing_parties=persist_filing_parties,
            ticker_list_filter=ticker_list_filter,
            form_list_filter=form_list_filter,
            ticker_list_filter_explicit=ticker_list_filter_explicit,
            form_list_filter_explicit=form_list_filter_explicit,
            issuer_tickers=list(issuer_tickers) or None,
            issuer_ciks=list(issuer_ciks) or None,
            entity_ciks=list(entity_ciks) or None,
            forms=list(forms) or None,
            form_families=[value.lower() for value in form_families] or None,
            date_from=date_from,
            date_to=date_to,
        )
    except FileNotFoundError as exc:
        message = str(exc)
        if "Merged index file not found:" in message:
            raise click.ClickException(f"{message} Run `py-sec-edgar index refresh` first.") from exc
        raise
    recent_activity = bounded_recent_activity(result.get("activity_events", []), window=DEFAULT_ACTIVITY_WINDOW)
    if verbose and not quiet:
        click.echo(render_activity_block(recent_activity, window=DEFAULT_ACTIVITY_WINDOW), err=True)
    if summary_json:
        click.echo(json.dumps(result, sort_keys=True))
        return

    if quiet:
        click.echo("Backfill complete.")
        return

    summary = render_summary_block(
        "Backfill candidate load complete.",
        {
            "candidate_count": result["candidate_count"],
            "download_attempted_count": result["download_attempted_count"],
            "download_succeeded_count": result["download_succeeded_count"],
            "download_failed_count": result["download_failed_count"],
            "download_failure_reason_counts": result.get("download_failure_reason_counts"),
            "download_failure_status_code_counts": result.get("download_failure_status_code_counts"),
            "extraction_attempted_count": result["extraction_attempted_count"],
            "extraction_succeeded_count": result["extraction_succeeded_count"],
            "extraction_failed_count": result["extraction_failed_count"],
            "filing_party_candidate_count": result.get("filing_party_candidate_count"),
            "filing_party_attempted_count": result.get("filing_party_attempted_count"),
            "filing_party_zero_record_count": result.get("filing_party_zero_record_count"),
            "filing_party_successful_nonzero_record_filing_count": result.get(
                "filing_party_successful_nonzero_record_filing_count"
            ),
            "filing_party_failed_count": result.get("filing_party_failed_count"),
            "filing_party_record_count": result["filing_party_record_count"],
            "filing_party_persisted_count": result["filing_party_persisted_count"],
            "selection_elapsed_seconds": result.get("selection_elapsed_seconds"),
            "download_elapsed_seconds": result.get("download_elapsed_seconds"),
            "extraction_elapsed_seconds": result.get("extraction_elapsed_seconds"),
            "total_elapsed_seconds": result.get("total_elapsed_seconds"),
        },
    )
    click.echo(summary)
    persist_path = result.get("filing_party_persist_path")
    if persist_path:
        click.echo(f"- filing_party_persist_path: {persist_path}")


if __name__ == "__main__":
    main()
