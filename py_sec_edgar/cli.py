from __future__ import annotations

import json
from pathlib import Path
import time
import tomllib

import click
from click.core import ParameterSource
import pandas as pd

from m_cache_shared.cli_helpers import load_json_object_input
from m_cache_shared.packers import build_run_status_view
from py_sec_edgar.api.service import FilingRetrievalService
from py_sec_edgar.augmentation_wave3 import (
    SHARED_AUGMENTATION_TYPES,
    build_api_augmentation_meta,
    list_shared_augmentation_artifacts,
    load_shared_augmentation_events,
    load_shared_augmentation_runs,
    map_to_shared_augmentation_type,
    materialize_shared_augmentation_metadata,
)
from py_sec_edgar.canonical_output import build_canonical_summary, counters_from_result, utc_now_iso
from py_sec_edgar.config import load_config
from py_sec_edgar.filters import FORM_FAMILY_MAP
from py_sec_edgar.filing_parties_query import (
    apply_limit_and_columns,
    load_filing_parties_parquet,
    parse_columns_option,
    query_filing_parties,
)
from py_sec_edgar.logging_utils import configure_logging
from py_sec_edgar.m_cache_config import effective_config_to_app_config, load_m_cache_effective_config
from py_sec_edgar.provider_ops import effective_provider_cfg, list_providers, show_provider
from py_sec_edgar.lookup import (
    apply_limit_and_columns as apply_lookup_limit_and_columns,
    load_lookup_dataframe,
    parse_columns_option as parse_lookup_columns_option,
    query_lookup,
    refresh_local_lookup_indexes,
)
from py_sec_edgar.monitoring import run_monitor_loop, run_monitor_poll
from py_sec_edgar.pipelines.backfill import run_backfill
from py_sec_edgar.pipelines.index_refresh import run_index_refresh
from py_sec_edgar.pipelines.refdata_refresh import run_refdata_refresh
from py_sec_edgar.progress import ProgressHeartbeat, progress_enabled, progress_machine_enabled, progress_payload_from_result
from py_sec_edgar.reconciliation import run_reconciliation
from py_sec_edgar.runtime_output import (
    DEFAULT_ACTIVITY_WINDOW,
    bounded_recent_activity,
    render_activity_block,
    render_summary_block,
)
from py_sec_edgar.wave4_shared.helpers import deterministic_source_text_version
from py_sec_edgar.wave4_shared.validators import (
    validate_producer_artifact_submission,
    validate_producer_run_submission,
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
@click.option(
    "--progress-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable NDJSON progress events to stderr.",
)
@click.option(
    "--progress-heartbeat-seconds",
    type=click.FloatRange(min=0.0),
    default=0.0,
    show_default=True,
    help="Emit machine liveness heartbeat events to stderr only when idle for this many seconds (0 disables).",
)
@click.option(
    "--output-schema",
    type=click.Choice(["legacy", "canonical"], case_sensitive=False),
    default="legacy",
    show_default=True,
    help="Summary/progress schema for machine outputs.",
)
def lookup_refresh(
    include_global_filings: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
    output_schema: str,
) -> None:
    output_schema = output_schema.lower()
    config = load_config()
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="lookup.refresh",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema=output_schema,
        domain="sec" if output_schema == "canonical" else None,
        command_path=["py-sec-edgar", "lookup", "refresh"] if output_schema == "canonical" else None,
    )
    try:
        with progress:
            result = refresh_local_lookup_indexes(
                config,
                include_global_filings=include_global_filings,
                progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
            )
            progress.set_counters(
                **progress_payload_from_result(
                    result,
                    keys=[
                        "placement_row_count",
                        "local_placement_row_count",
                        "filings_row_count",
                        "artifacts_row_count",
                    ],
                )
            )
    except FileNotFoundError as exc:
        message = str(exc)
        if "Merged index file not found:" in message:
            raise click.ClickException(f"{message} Run `py-sec-edgar index refresh` first.") from exc
        raise click.ClickException(message) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except KeyboardInterrupt as exc:
        raise click.ClickException("Interrupted by user.") from exc

    if summary_json:
        if output_schema == "canonical":
            finished_at = utc_now_iso()
            counters = counters_from_result(
                result,
                key_map={
                    "placement_row_count": "candidate_count",
                    "local_placement_row_count": "attempted_count",
                    "filings_row_count": "succeeded_count",
                    "artifacts_row_count": "persisted_count",
                },
            )
            payload = build_canonical_summary(
                status="ok",
                domain="sec",
                command_path=["py-sec-edgar", "lookup", "refresh"],
                started_at=started_at,
                finished_at=finished_at,
                elapsed_seconds=float(result.get("elapsed_seconds", 0.0)),
                resolution_mode=None,
                remote_attempted=False,
                provider_requested=None,
                provider_used=None,
                rate_limited=False,
                retry_count=0,
                persisted_locally=True,
                counters=counters,
            )
            click.echo(json.dumps(payload, sort_keys=True))
        else:
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


@main.group("monitor")
def monitor_group() -> None:
    """Feed-driven monitoring and cache-warming operations."""


@monitor_group.command("poll")
@click.option("--warm/--no-warm", default=True, show_default=True, help="Warm local SEC mirror cache for detected candidates.")
@click.option("--form-type", "form_types", multiple=True, help="Filter by form type. Repeat for multiple values.")
@click.option(
    "--form-family",
    "form_families",
    type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False),
    multiple=True,
    help="Filter by form family. Repeat for multiple values.",
)
@click.option("--issuer-cik", "issuer_ciks", multiple=True, help="Filter by issuer CIK. Repeat for multiple values.")
@click.option("--entity-cik", "entity_ciks", multiple=True, help="Filter by entity CIK. Repeat for multiple values.")
@click.option("--date-from", default=None, help="Lower filing date bound (inclusive), e.g. 2025-01-01.")
@click.option("--date-to", default=None, help="Upper filing date bound (inclusive), e.g. 2025-03-31.")
@click.option(
    "--execute-extraction/--no-execute-extraction",
    default=False,
    show_default=True,
    help="Run extraction for monitor-warmed filings.",
)
@click.option(
    "--persist-filing-parties/--no-persist-filing-parties",
    default=False,
    show_default=True,
    help="Persist filing-party rows for monitor-warmed supported filings.",
)
@click.option(
    "--refresh-lookup/--no-refresh-lookup",
    default=True,
    show_default=True,
    help="Refresh local lookup artifacts if monitor run changed local visibility.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON summary instead of human-readable lines.",
)
@click.option(
    "--progress-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable NDJSON progress events to stderr.",
)
@click.option(
    "--progress-heartbeat-seconds",
    type=click.FloatRange(min=0.0),
    default=0.0,
    show_default=True,
    help="Emit machine liveness heartbeat events to stderr only when idle for this many seconds (0 disables).",
)
@click.option(
    "--output-schema",
    type=click.Choice(["legacy", "canonical"], case_sensitive=False),
    default="legacy",
    show_default=True,
    help="Summary/progress schema for machine outputs.",
)
def monitor_poll(
    warm: bool,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    entity_ciks: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    execute_extraction: bool,
    persist_filing_parties: bool,
    refresh_lookup: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
    output_schema: str,
) -> None:
    output_schema = output_schema.lower()
    config = load_config()
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="monitor.poll",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema=output_schema,
        domain="sec" if output_schema == "canonical" else None,
        command_path=["py-sec-edgar", "monitor", "poll"] if output_schema == "canonical" else None,
    )
    try:
        with progress:
            result = run_monitor_poll(
                config,
                warm=warm,
                form_types=list(form_types) or None,
                form_families=[value.lower() for value in form_families] or None,
                issuer_ciks=list(issuer_ciks) or None,
                entity_ciks=list(entity_ciks) or None,
                date_from=date_from,
                date_to=date_to,
                execute_extraction=execute_extraction,
                persist_filing_parties=persist_filing_parties,
                refresh_lookup=refresh_lookup,
                progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
            )
            progress.set_counters(
                **progress_payload_from_result(
                    result,
                    keys=[
                        "detected_candidate_count",
                        "filtered_candidate_count",
                        "warm_attempted_count",
                        "warm_succeeded_count",
                        "warm_failed_count",
                    ],
                )
            )
    except KeyboardInterrupt as exc:
        raise click.ClickException("Interrupted by user.") from exc

    if summary_json:
        if output_schema == "canonical":
            finished_at = utc_now_iso()
            counters = counters_from_result(
                result,
                key_map={
                    "detected_candidate_count": "candidate_count",
                    "warm_attempted_count": "attempted_count",
                    "warm_succeeded_count": "succeeded_count",
                    "warm_failed_count": "failed_count",
                },
            )
            payload = build_canonical_summary(
                status="ok",
                domain="sec",
                command_path=["py-sec-edgar", "monitor", "poll"],
                started_at=started_at,
                finished_at=finished_at,
                elapsed_seconds=float(result.get("total_elapsed_seconds", 0.0)),
                resolution_mode=None,
                remote_attempted=bool(result.get("warm_attempted_count", 0)),
                provider_requested="sec",
                provider_used="sec",
                rate_limited=False,
                retry_count=0,
                persisted_locally=bool(result.get("warm_succeeded_count", 0)),
                counters=counters,
            )
            click.echo(json.dumps(payload, sort_keys=True))
        else:
            click.echo(json.dumps(result, sort_keys=True))
        return

    summary = render_summary_block(
        "Monitor poll complete.",
        {
            "detected_candidate_count": result.get("detected_candidate_count"),
            "filtered_candidate_count": result.get("filtered_candidate_count"),
            "seen_duplicate_count": result.get("seen_duplicate_count"),
            "warm_attempted_count": result.get("warm_attempted_count"),
            "warm_succeeded_count": result.get("warm_succeeded_count"),
            "warm_failed_count": result.get("warm_failed_count"),
            "skipped_already_local_count": result.get("skipped_already_local_count"),
            "lookup_refresh_attempted": result.get("lookup_refresh_attempted"),
            "lookup_refresh_performed": result.get("lookup_refresh_performed"),
            "lookup_refresh_skipped_reason": result.get("lookup_refresh_skipped_reason"),
            "local_visibility_changed": result.get("local_visibility_changed"),
            "seen_state_path": result.get("seen_state_path"),
            "events_path": result.get("events_path"),
            "total_elapsed_seconds": result.get("total_elapsed_seconds"),
        },
    )
    click.echo(summary)


@monitor_group.command("loop")
@click.option("--warm/--no-warm", default=True, show_default=True, help="Warm local SEC mirror cache for detected candidates.")
@click.option("--form-type", "form_types", multiple=True, help="Filter by form type. Repeat for multiple values.")
@click.option(
    "--form-family",
    "form_families",
    type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False),
    multiple=True,
    help="Filter by form family. Repeat for multiple values.",
)
@click.option("--issuer-cik", "issuer_ciks", multiple=True, help="Filter by issuer CIK. Repeat for multiple values.")
@click.option("--entity-cik", "entity_ciks", multiple=True, help="Filter by entity CIK. Repeat for multiple values.")
@click.option("--date-from", default=None, help="Lower filing date bound (inclusive), e.g. 2025-01-01.")
@click.option("--date-to", default=None, help="Upper filing date bound (inclusive), e.g. 2025-03-31.")
@click.option(
    "--execute-extraction/--no-execute-extraction",
    default=False,
    show_default=True,
    help="Run extraction for monitor-warmed filings.",
)
@click.option(
    "--persist-filing-parties/--no-persist-filing-parties",
    default=False,
    show_default=True,
    help="Persist filing-party rows for monitor-warmed supported filings.",
)
@click.option(
    "--refresh-lookup/--no-refresh-lookup",
    default=True,
    show_default=True,
    help="Refresh local lookup artifacts if monitor run changed local visibility.",
)
@click.option(
    "--interval-seconds",
    type=click.FloatRange(min=0.0),
    default=30.0,
    show_default=True,
    help="Sleep interval between poll iterations.",
)
@click.option(
    "--max-iterations",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="Maximum loop iterations before exiting.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON summary for the bounded loop run.",
)
def monitor_loop(
    warm: bool,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    entity_ciks: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    execute_extraction: bool,
    persist_filing_parties: bool,
    refresh_lookup: bool,
    interval_seconds: float,
    max_iterations: int,
    summary_json: bool,
) -> None:
    config = load_config()
    result = run_monitor_loop(
        config,
        interval_seconds=interval_seconds,
        max_iterations=max_iterations,
        warm=warm,
        form_types=list(form_types) or None,
        form_families=[value.lower() for value in form_families] or None,
        issuer_ciks=list(issuer_ciks) or None,
        entity_ciks=list(entity_ciks) or None,
        date_from=date_from,
        date_to=date_to,
        execute_extraction=execute_extraction,
        persist_filing_parties=persist_filing_parties,
        refresh_lookup=refresh_lookup,
    )

    if summary_json:
        click.echo(json.dumps(result, sort_keys=True))
        return

    summary = render_summary_block(
        "Monitor loop complete.",
        {
            "iterations_run": result.get("iterations_run"),
            "interval_seconds": result.get("interval_seconds"),
            "total_detected_candidate_count": result.get("total_detected_candidate_count"),
            "total_filtered_candidate_count": result.get("total_filtered_candidate_count"),
            "total_warm_attempted_count": result.get("total_warm_attempted_count"),
            "total_warm_succeeded_count": result.get("total_warm_succeeded_count"),
            "total_warm_failed_count": result.get("total_warm_failed_count"),
            "total_elapsed_seconds": result.get("total_elapsed_seconds"),
        },
    )
    click.echo(summary)


@main.group("reconcile")
def reconcile_group() -> None:
    """Feed-plus-index reconciliation operations."""


@reconcile_group.command("run")
@click.option(
    "--recent-days",
    type=click.IntRange(min=0),
    default=None,
    help="Recent-day window when --date-from is not provided.",
)
@click.option("--date-from", default=None, help="Lower filing date bound (inclusive), e.g. 2025-01-01.")
@click.option("--date-to", default=None, help="Upper filing date bound (inclusive), e.g. 2025-03-31.")
@click.option("--form-type", "form_types", multiple=True, help="Filter by form type. Repeat for multiple values.")
@click.option(
    "--form-family",
    "form_families",
    type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False),
    multiple=True,
    help="Filter by form family. Repeat for multiple values.",
)
@click.option("--issuer-cik", "issuer_ciks", multiple=True, help="Filter by issuer CIK. Repeat for multiple values.")
@click.option(
    "--catch-up-warm/--no-catch-up-warm",
    default=False,
    show_default=True,
    help="Warm missing local submissions for catch-up eligible reconciliation rows.",
)
@click.option(
    "--refresh-lookup/--no-refresh-lookup",
    default=True,
    show_default=True,
    help="Refresh/update lookup visibility after successful catch-up warm activity.",
)
@click.option(
    "--summary-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON summary instead of human-readable lines.",
)
@click.option(
    "--progress-json",
    is_flag=True,
    default=False,
    help="Emit machine-readable NDJSON progress events to stderr.",
)
@click.option(
    "--progress-heartbeat-seconds",
    type=click.FloatRange(min=0.0),
    default=0.0,
    show_default=True,
    help="Emit machine liveness heartbeat events to stderr only when idle for this many seconds (0 disables).",
)
@click.option(
    "--output-schema",
    type=click.Choice(["legacy", "canonical"], case_sensitive=False),
    default="legacy",
    show_default=True,
    help="Summary/progress schema for machine outputs.",
)
def reconcile_run(
    recent_days: int | None,
    date_from: str | None,
    date_to: str | None,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    catch_up_warm: bool,
    refresh_lookup: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
    output_schema: str,
) -> None:
    output_schema = output_schema.lower()
    config = load_config()
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="reconcile.run",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema=output_schema,
        domain="sec" if output_schema == "canonical" else None,
        command_path=["py-sec-edgar", "reconcile", "run"] if output_schema == "canonical" else None,
    )
    try:
        with progress:
            result = run_reconciliation(
                config,
                recent_days=recent_days,
                date_from=date_from,
                date_to=date_to,
                form_types=list(form_types) or None,
                form_families=[value.lower() for value in form_families] or None,
                issuer_ciks=list(issuer_ciks) or None,
                catch_up_warm=catch_up_warm,
                refresh_lookup=refresh_lookup,
                progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
            )
            progress.set_counters(
                **progress_payload_from_result(
                    result,
                    keys=[
                        "reconciled_row_count",
                        "catch_up_attempted_count",
                        "catch_up_succeeded_count",
                        "catch_up_failed_count",
                        "catch_up_skipped_count",
                    ],
                )
            )
    except KeyboardInterrupt as exc:
        raise click.ClickException("Interrupted by user.") from exc

    if summary_json:
        if output_schema == "canonical":
            finished_at = utc_now_iso()
            counters = counters_from_result(
                result,
                key_map={
                    "reconciled_row_count": "candidate_count",
                    "catch_up_attempted_count": "attempted_count",
                    "catch_up_succeeded_count": "succeeded_count",
                    "catch_up_failed_count": "failed_count",
                    "catch_up_skipped_count": "skipped_count",
                },
            )
            counters["discrepancy_count"] = int(result.get("reconciled_row_count", 0))
            payload = build_canonical_summary(
                status="ok",
                domain="sec",
                command_path=["py-sec-edgar", "reconcile", "run"],
                started_at=started_at,
                finished_at=finished_at,
                elapsed_seconds=float(result.get("total_elapsed_seconds", 0.0)),
                resolution_mode=None,
                remote_attempted=bool(result.get("catch_up_attempted_count", 0)),
                provider_requested="sec",
                provider_used="sec",
                rate_limited=False,
                retry_count=0,
                persisted_locally=bool(result.get("catch_up_succeeded_count", 0)),
                counters=counters,
            )
            click.echo(json.dumps(payload, sort_keys=True))
        else:
            click.echo(json.dumps(result, sort_keys=True))
        return

    summary = render_summary_block(
        "Reconciliation run complete.",
        {
            "merged_index_candidate_count": result.get("merged_index_candidate_count"),
            "feed_candidate_count": result.get("feed_candidate_count"),
            "reconciled_row_count": result.get("reconciled_row_count"),
            "discrepancy_type_counts": result.get("discrepancy_type_counts"),
            "catch_up_warm_enabled": result.get("catch_up_warm_enabled"),
            "catch_up_attempted_count": result.get("catch_up_attempted_count"),
            "catch_up_succeeded_count": result.get("catch_up_succeeded_count"),
            "catch_up_failed_count": result.get("catch_up_failed_count"),
            "lookup_update_mode": result.get("lookup_update_mode"),
            "lookup_refresh_performed": result.get("lookup_refresh_performed"),
            "lookup_refresh_skipped_reason": result.get("lookup_refresh_skipped_reason"),
            "discrepancies_path": result.get("discrepancies_path"),
            "events_path": result.get("events_path"),
            "total_elapsed_seconds": result.get("total_elapsed_seconds"),
        },
    )
    click.echo(summary)


@main.group("augmentations")
def augmentations_group() -> None:
    """Reviewer/operator augmentation inspection commands."""


@main.group("aug")
def aug_group() -> None:
    """Canonical short-name alias for augmentation commands."""


def _echo_rows(rows: list[dict[str, object]], *, as_json: bool, empty_message: str) -> None:
    if as_json:
        click.echo(json.dumps(rows, sort_keys=True))
        return
    if not rows:
        click.echo(empty_message)
        return
    frame = pd.DataFrame(rows)
    click.echo(frame.to_string(index=False))


def _load_aug_payload_or_fail(
    *,
    payload_json: str | None,
    payload_file: Path | None,
) -> dict[str, object]:
    try:
        return load_json_object_input(payload_json=payload_json, payload_file=payload_file)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@augmentations_group.command("events")
@click.option("--accession-number", "accession_numbers", multiple=True, help="Optional accession filter. Repeatable.")
@click.option("--submission-id", default=None, help="Optional submission filter.")
@click.option("--producer-id", default=None, help="Optional producer filter.")
@click.option("--layer-type", default=None, help="Optional layer filter.")
@click.option("--event-family", default=None, help="Optional event family filter.")
@click.option("--event-type", default=None, help="Optional event type filter.")
@click.option("--event-source", default=None, help="Optional event source filter.")
@click.option("--warning-code", default=None, help="Optional governance warning code filter.")
@click.option("--match-status", default=None, help="Optional governance match status filter.")
@click.option("--to-state", default=None, help="Optional lifecycle to_state filter.")
@click.option("--event-time-from", default=None, help="Optional event time lower bound.")
@click.option("--event-time-to", default=None, help="Optional event time upper bound.")
@click.option("--received-at-from", default=None, help="Backward-compatible alias for --event-time-from.")
@click.option("--received-at-to", default=None, help="Backward-compatible alias for --event-time-to.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit API-shaped JSON payload.")
def augmentations_events(
    accession_numbers: tuple[str, ...],
    submission_id: str | None,
    producer_id: str | None,
    layer_type: str | None,
    event_family: str | None,
    event_type: str | None,
    event_source: str | None,
    warning_code: str | None,
    match_status: str | None,
    to_state: str | None,
    event_time_from: str | None,
    event_time_to: str | None,
    received_at_from: str | None,
    received_at_to: str | None,
    limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        rows = service.list_augmentation_events(
            accession_numbers=list(accession_numbers) or None,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=event_family,
            event_type=event_type,
            event_source=event_source,
            warning_code=warning_code,
            match_status=match_status,
            to_state=to_state,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            limit=limit,
        )
    except (LookupError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"events": rows}
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    _echo_rows(payload["events"], as_json=False, empty_message="No events found.")


@augmentations_group.command("filing-events")
@click.argument("accession_number")
@click.option("--submission-id", default=None, help="Optional submission filter.")
@click.option("--producer-id", default=None, help="Optional producer filter.")
@click.option("--layer-type", default=None, help="Optional layer filter.")
@click.option("--event-family", default=None, help="Optional event family filter.")
@click.option("--event-type", default=None, help="Optional event type filter.")
@click.option("--event-source", default=None, help="Optional event source filter.")
@click.option("--warning-code", default=None, help="Optional governance warning code filter.")
@click.option("--match-status", default=None, help="Optional governance match status filter.")
@click.option("--to-state", default=None, help="Optional lifecycle to_state filter.")
@click.option("--event-time-from", default=None, help="Optional event time lower bound.")
@click.option("--event-time-to", default=None, help="Optional event time upper bound.")
@click.option("--received-at-from", default=None, help="Backward-compatible alias for --event-time-from.")
@click.option("--received-at-to", default=None, help="Backward-compatible alias for --event-time-to.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit API-shaped JSON payload.")
def augmentations_filing_events(
    accession_number: str,
    submission_id: str | None,
    producer_id: str | None,
    layer_type: str | None,
    event_family: str | None,
    event_type: str | None,
    event_source: str | None,
    warning_code: str | None,
    match_status: str | None,
    to_state: str | None,
    event_time_from: str | None,
    event_time_to: str | None,
    received_at_from: str | None,
    received_at_to: str | None,
    limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        rows = service.list_augmentation_events(
            accession_numbers=[accession_number],
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=event_family,
            event_type=event_type,
            event_source=event_source,
            warning_code=warning_code,
            match_status=match_status,
            to_state=to_state,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            limit=limit,
        )
    except (LookupError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"events": rows}
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    _echo_rows(payload["events"], as_json=False, empty_message="No events found.")


@augmentations_group.command("events-summary")
@click.option("--accession-number", "accession_numbers", multiple=True, help="Optional accession filter. Repeatable.")
@click.option("--submission-id", default=None, help="Optional submission filter.")
@click.option("--producer-id", default=None, help="Optional producer filter.")
@click.option("--layer-type", default=None, help="Optional layer filter.")
@click.option("--event-family", default=None, help="Optional event family filter.")
@click.option("--event-type", default=None, help="Optional event type filter.")
@click.option("--event-source", default=None, help="Optional event source filter.")
@click.option("--warning-code", default=None, help="Optional governance warning code filter.")
@click.option("--match-status", default=None, help="Optional governance match status filter.")
@click.option("--to-state", default=None, help="Optional lifecycle to_state filter.")
@click.option("--event-time-from", default=None, help="Optional event time lower bound.")
@click.option("--event-time-to", default=None, help="Optional event time upper bound.")
@click.option("--received-at-from", default=None, help="Backward-compatible alias for --event-time-from.")
@click.option("--received-at-to", default=None, help="Backward-compatible alias for --event-time-to.")
@click.option("--group-by", "group_by", multiple=True, help="Grouping dimension. Repeatable.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit API-shaped JSON payload.")
def augmentations_events_summary(
    accession_numbers: tuple[str, ...],
    submission_id: str | None,
    producer_id: str | None,
    layer_type: str | None,
    event_family: str | None,
    event_type: str | None,
    event_source: str | None,
    warning_code: str | None,
    match_status: str | None,
    to_state: str | None,
    event_time_from: str | None,
    event_time_to: str | None,
    received_at_from: str | None,
    received_at_to: str | None,
    group_by: tuple[str, ...],
    limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        rows = service.summarize_augmentation_events(
            accession_numbers=list(accession_numbers) or None,
            submission_id=submission_id,
            producer_id=producer_id,
            layer_type=layer_type,
            event_family=event_family,
            event_type=event_type,
            event_source=event_source,
            warning_code=warning_code,
            match_status=match_status,
            to_state=to_state,
            event_time_from=event_time_from,
            event_time_to=event_time_to,
            received_at_from=received_at_from,
            received_at_to=received_at_to,
            group_by=list(group_by) or None,
            limit=limit,
        )
    except (LookupError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"rows": rows}
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    _echo_rows(payload["rows"], as_json=False, empty_message="No summary rows found.")


@augmentations_group.command("submission")
@click.argument("submission_id")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_submission(submission_id: str, as_json: bool) -> None:
    service = FilingRetrievalService(load_config())
    try:
        payload = service.get_augmentation_submission_detail(submission_id=submission_id)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(render_summary_block(f"Submission {submission_id}", payload))


@augmentations_group.command("lifecycle-events")
@click.argument("submission_id")
@click.option("--limit", type=click.IntRange(min=0), default=50, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_lifecycle_events(submission_id: str, limit: int, as_json: bool) -> None:
    service = FilingRetrievalService(load_config())
    try:
        rows = service.list_submission_lifecycle_events(submission_id=submission_id, limit=limit)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo_rows(rows, as_json=as_json, empty_message="No lifecycle events found.")


@augmentations_group.command("governance-summary")
@click.argument("submission_id")
@click.option("--limit", type=click.IntRange(min=0), default=50, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_governance_summary(submission_id: str, limit: int, as_json: bool) -> None:
    service = FilingRetrievalService(load_config())
    rows = service.summarize_governance_events(submission_id=submission_id, limit=limit)
    _echo_rows(rows, as_json=as_json, empty_message="No governance summary rows found.")


@augmentations_group.command("governance-events")
@click.argument("submission_id")
@click.option("--limit", type=click.IntRange(min=0), default=50, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_governance_events(submission_id: str, limit: int, as_json: bool) -> None:
    service = FilingRetrievalService(load_config())
    rows = service.list_governance_events(submission_id=submission_id, limit=limit)
    _echo_rows(rows, as_json=as_json, empty_message="No governance events found.")


@augmentations_group.command("overlay-impact")
@click.argument("submission_id")
@click.option("--accession-number", "accession_numbers", multiple=True, help="Optional accession filter. Repeatable.")
@click.option("--limit", type=click.IntRange(min=0), default=50, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_overlay_impact(
    submission_id: str,
    accession_numbers: tuple[str, ...],
    limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        payload = service.list_submission_overlay_impact(
            submission_id=submission_id,
            accession_numbers=list(accession_numbers) or None,
            limit=limit,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(
        render_summary_block(
            f"Overlay impact for {submission_id}",
            {
                "selection_policy": payload.get("selection_policy"),
                "affected_accession_count": payload.get("affected_accession_count"),
                "contributing_accession_count": payload.get("contributing_accession_count"),
                "non_contributing_accession_count": payload.get("non_contributing_accession_count"),
            },
        )
    )
    _echo_rows(payload.get("rows", []), as_json=False, empty_message="No overlay impact rows found.")


@augmentations_group.command("entity-impact")
@click.argument("submission_id")
@click.option("--accession-number", "accession_numbers", multiple=True, help="Optional accession filter. Repeatable.")
@click.option("--limit", type=click.IntRange(min=0), default=50, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_entity_impact(
    submission_id: str,
    accession_numbers: tuple[str, ...],
    limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        payload = service.list_submission_entity_impact(
            submission_id=submission_id,
            accession_numbers=list(accession_numbers) or None,
            limit=limit,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(
        render_summary_block(
            f"Entity impact for {submission_id}",
            {
                "entity_index_present": payload.get("entity_index_present"),
                "row_count": payload.get("row_count"),
                "accession_count": payload.get("accession_count"),
            },
        )
    )
    _echo_rows(payload.get("rows", []), as_json=False, empty_message="No entity impact rows found.")


@augmentations_group.command("review-bundle")
@click.argument("submission_id")
@click.option("--overlay-limit", type=click.IntRange(min=0), default=50, show_default=True, help="Overlay-impact row cap.")
@click.option("--entity-limit", type=click.IntRange(min=0), default=50, show_default=True, help="Entity-impact row cap.")
@click.option("--lifecycle-limit", type=click.IntRange(min=0), default=50, show_default=True, help="Lifecycle-event row cap.")
@click.option("--governance-limit", type=click.IntRange(min=0), default=50, show_default=True, help="Governance-summary row cap.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def augmentations_review_bundle(
    submission_id: str,
    overlay_limit: int,
    entity_limit: int,
    lifecycle_limit: int,
    governance_limit: int,
    as_json: bool,
) -> None:
    service = FilingRetrievalService(load_config())
    try:
        payload = service.get_submission_review_bundle(
            submission_id=submission_id,
            overlay_limit=overlay_limit,
            entity_limit=entity_limit,
            lifecycle_limit=lifecycle_limit,
            governance_limit=governance_limit,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(
        render_summary_block(
            f"Review bundle for {submission_id}",
            {
                "lifecycle_state": payload["submission"].get("lifecycle_state"),
                "warning_item_count": payload["submission"].get("warning_item_count"),
                "overlay_impact_returned_count": payload["overlay_impact"].get("returned_count"),
                "entity_impact_returned_count": payload["entity_impact"].get("returned_count"),
            },
        )
    )


for _command_name, _command in augmentations_group.commands.items():
    aug_group.add_command(_command, _command_name)


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


@click.group("m-cache")
def m_cache_main() -> None:
    """Canonical shared command surface."""


@m_cache_main.group("sec")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True),
    default=None,
    help="Path to m-cache.toml.",
)
@click.pass_context
def m_cache_sec_group(ctx: click.Context, config_path: Path | None) -> None:
    try:
        effective = load_m_cache_effective_config(config_path=config_path)
        runtime_config = effective_config_to_app_config(effective)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    ctx.ensure_object(dict)
    ctx.obj["m_cache_effective_config"] = effective
    ctx.obj["m_cache_runtime_config"] = runtime_config


def _m_cache_runtime_config(ctx: click.Context):
    cfg = (ctx.obj or {}).get("m_cache_runtime_config")
    if cfg is None:
        raise click.ClickException("m-cache sec runtime config was not initialized.")
    return cfg


def _m_cache_effective_config(ctx: click.Context):
    cfg = (ctx.obj or {}).get("m_cache_effective_config")
    if cfg is None:
        raise click.ClickException("m-cache sec effective config was not initialized.")
    return cfg


@m_cache_sec_group.group("refdata")
def m_cache_refdata_group() -> None:
    """Reference-data operations."""


@m_cache_refdata_group.command("refresh")
@click.pass_context
@click.option("--summary-json/--no-summary-json", default=True, show_default=True, help="Emit canonical summary JSON to stdout.")
@click.option("--progress-json/--no-progress-json", default=True, show_default=True, help="Emit canonical NDJSON progress events to stderr.")
@click.option(
    "--progress-heartbeat-seconds",
    type=click.FloatRange(min=0.0),
    default=0.0,
    show_default=True,
    help="Emit machine liveness heartbeat events when idle for this many seconds (0 disables).",
)
def m_cache_refdata_refresh(
    ctx: click.Context,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
) -> None:
    started_at = utc_now_iso()
    started_mono = time.monotonic()
    config = _m_cache_runtime_config(ctx)
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="refdata.refresh",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema="canonical",
        domain="sec",
        command_path=["m-cache", "sec", "refdata", "refresh"],
    )
    try:
        with progress:
            result = run_refdata_refresh(config)
            progress.set_counters(artifact_count=int(result.get("artifact_count", 0)))
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if summary_json:
        payload = build_canonical_summary(
            status="ok",
            domain="sec",
            command_path=["m-cache", "sec", "refdata", "refresh"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=float(result.get("elapsed_seconds", round(time.monotonic() - started_mono, 3))),
            resolution_mode=None,
            remote_attempted=False,
            provider_requested=None,
            provider_used=None,
            rate_limited=False,
            retry_count=0,
            persisted_locally=True,
            counters={"persisted_count": int(result.get("artifact_count", 0))},
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("m-cache sec refdata refresh complete.")


@m_cache_sec_group.group("lookup")
def m_cache_lookup_group() -> None:
    """Lookup operations."""


@m_cache_lookup_group.command("refresh")
@click.pass_context
@click.option("--include-global-filings/--no-include-global-filings", default=False, show_default=True)
@click.option("--summary-json/--no-summary-json", default=True, show_default=True, help="Emit canonical summary JSON to stdout.")
@click.option("--progress-json/--no-progress-json", default=True, show_default=True, help="Emit canonical NDJSON progress events to stderr.")
@click.option(
    "--progress-heartbeat-seconds",
    type=click.FloatRange(min=0.0),
    default=0.0,
    show_default=True,
    help="Emit machine liveness heartbeat events when idle for this many seconds (0 disables).",
)
def m_cache_lookup_refresh(
    ctx: click.Context,
    include_global_filings: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
) -> None:
    config = _m_cache_runtime_config(ctx)
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="lookup.refresh",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema="canonical",
        domain="sec",
        command_path=["m-cache", "sec", "lookup", "refresh"],
    )
    try:
        with progress:
            result = refresh_local_lookup_indexes(
                config,
                include_global_filings=include_global_filings,
                progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
            )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if summary_json:
        counters = counters_from_result(
            result,
            key_map={
                "placement_row_count": "candidate_count",
                "local_placement_row_count": "attempted_count",
                "filings_row_count": "succeeded_count",
                "artifacts_row_count": "persisted_count",
            },
        )
        payload = build_canonical_summary(
            status="ok",
            domain="sec",
            command_path=["m-cache", "sec", "lookup", "refresh"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=float(result.get("elapsed_seconds", 0.0)),
            resolution_mode=None,
            remote_attempted=False,
            provider_requested=None,
            provider_used=None,
            rate_limited=False,
            retry_count=0,
            persisted_locally=True,
            counters=counters,
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("m-cache sec lookup refresh complete.")


@m_cache_lookup_group.command("query")
@click.pass_context
@click.option(
    "--scope",
    type=click.Choice(["filings", "artifacts"], case_sensitive=False),
    default="filings",
    show_default=True,
)
@click.option("--accession-number", "accession_numbers", multiple=True)
@click.option("--cik", "ciks", multiple=True)
@click.option("--form-type", "form_types", multiple=True)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--artifact-type", "artifact_types", multiple=True)
@click.option("--path-contains", default=None)
@click.option("--all", "all_filings", is_flag=True, default=False)
@click.option("--limit", type=click.IntRange(min=0), default=None)
@click.option("--columns", default=None)
@click.option("--json", "as_json", is_flag=True, default=True)
def m_cache_lookup_query(
    ctx: click.Context,
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
    config = _m_cache_runtime_config(ctx)
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
    click.echo(filtered.to_string(index=False) if not filtered.empty else "No lookup rows matched.")


@m_cache_sec_group.group("monitor")
def m_cache_monitor_group() -> None:
    """Feed-driven monitor operations."""


@m_cache_monitor_group.command("poll")
@click.pass_context
@click.option("--warm/--no-warm", default=True, show_default=True)
@click.option("--form-type", "form_types", multiple=True)
@click.option("--form-family", "form_families", type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False), multiple=True)
@click.option("--issuer-cik", "issuer_ciks", multiple=True)
@click.option("--entity-cik", "entity_ciks", multiple=True)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--execute-extraction/--no-execute-extraction", default=False, show_default=True)
@click.option("--persist-filing-parties/--no-persist-filing-parties", default=False, show_default=True)
@click.option("--refresh-lookup/--no-refresh-lookup", default=True, show_default=True)
@click.option("--summary-json/--no-summary-json", default=True, show_default=True)
@click.option("--progress-json/--no-progress-json", default=True, show_default=True)
@click.option("--progress-heartbeat-seconds", type=click.FloatRange(min=0.0), default=0.0, show_default=True)
def m_cache_monitor_poll(
    ctx: click.Context,
    warm: bool,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    entity_ciks: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    execute_extraction: bool,
    persist_filing_parties: bool,
    refresh_lookup: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
) -> None:
    config = _m_cache_runtime_config(ctx)
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="monitor.poll",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema="canonical",
        domain="sec",
        command_path=["m-cache", "sec", "monitor", "poll"],
    )
    with progress:
        result = run_monitor_poll(
            config,
            warm=warm,
            form_types=list(form_types) or None,
            form_families=[value.lower() for value in form_families] or None,
            issuer_ciks=list(issuer_ciks) or None,
            entity_ciks=list(entity_ciks) or None,
            date_from=date_from,
            date_to=date_to,
            execute_extraction=execute_extraction,
            persist_filing_parties=persist_filing_parties,
            refresh_lookup=refresh_lookup,
            progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
        )
        progress.emit_event(
            phase="monitor.poll.result",
            counters={
                "attempted_count": int(result.get("warm_attempted_count", 0)),
                "succeeded_count": int(result.get("warm_succeeded_count", 0)),
                "failed_count": int(result.get("warm_failed_count", 0)),
            },
            provider="sec",
            rate_limit_state="ok",
        )

    if summary_json:
        counters = counters_from_result(
            result,
            key_map={
                "detected_candidate_count": "candidate_count",
                "warm_attempted_count": "attempted_count",
                "warm_succeeded_count": "succeeded_count",
                "warm_failed_count": "failed_count",
            },
        )
        payload = build_canonical_summary(
            status="ok",
            domain="sec",
            command_path=["m-cache", "sec", "monitor", "poll"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=float(result.get("total_elapsed_seconds", 0.0)),
            resolution_mode=None,
            remote_attempted=bool(result.get("warm_attempted_count", 0)),
            provider_requested="sec",
            provider_used="sec",
            rate_limited=False,
            retry_count=0,
            persisted_locally=bool(result.get("warm_succeeded_count", 0)),
            counters=counters,
            selection_outcome="used_requested_provider" if bool(result.get("warm_attempted_count", 0)) else "served_locally",
            served_from="remote_then_persisted" if bool(result.get("warm_succeeded_count", 0)) else "none",
            reason_code="remote_fetched" if bool(result.get("warm_succeeded_count", 0)) else "local_miss",
            rate_limit_state={"provider_id": "sec", "rate_limited": False, "deferred": False},
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return

    click.echo("m-cache sec monitor poll complete.")


@m_cache_monitor_group.command("loop")
@click.pass_context
@click.option("--warm/--no-warm", default=True, show_default=True)
@click.option("--form-type", "form_types", multiple=True)
@click.option("--form-family", "form_families", type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False), multiple=True)
@click.option("--issuer-cik", "issuer_ciks", multiple=True)
@click.option("--entity-cik", "entity_ciks", multiple=True)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--execute-extraction/--no-execute-extraction", default=False, show_default=True)
@click.option("--persist-filing-parties/--no-persist-filing-parties", default=False, show_default=True)
@click.option("--refresh-lookup/--no-refresh-lookup", default=True, show_default=True)
@click.option("--interval-seconds", type=click.FloatRange(min=0.0), default=30.0, show_default=True)
@click.option("--max-iterations", type=click.IntRange(min=1), default=5, show_default=True)
@click.option("--summary-json/--no-summary-json", default=True, show_default=True)
def m_cache_monitor_loop(
    ctx: click.Context,
    warm: bool,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    entity_ciks: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    execute_extraction: bool,
    persist_filing_parties: bool,
    refresh_lookup: bool,
    interval_seconds: float,
    max_iterations: int,
    summary_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    started_at = utc_now_iso()
    result = run_monitor_loop(
        config,
        interval_seconds=interval_seconds,
        max_iterations=max_iterations,
        warm=warm,
        form_types=list(form_types) or None,
        form_families=[value.lower() for value in form_families] or None,
        issuer_ciks=list(issuer_ciks) or None,
        entity_ciks=list(entity_ciks) or None,
        date_from=date_from,
        date_to=date_to,
        execute_extraction=execute_extraction,
        persist_filing_parties=persist_filing_parties,
        refresh_lookup=refresh_lookup,
    )
    if summary_json:
        counters = counters_from_result(
            result,
            key_map={
                "total_detected_candidate_count": "candidate_count",
                "total_warm_attempted_count": "attempted_count",
                "total_warm_succeeded_count": "succeeded_count",
                "total_warm_failed_count": "failed_count",
            },
        )
        counters["iterations_run"] = int(result.get("iterations_run", 0))
        payload = build_canonical_summary(
            status="ok",
            domain="sec",
            command_path=["m-cache", "sec", "monitor", "loop"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=float(result.get("total_elapsed_seconds", 0.0)),
            resolution_mode=None,
            remote_attempted=bool(result.get("total_warm_attempted_count", 0)),
            provider_requested="sec",
            provider_used="sec",
            rate_limited=False,
            retry_count=0,
            persisted_locally=bool(result.get("total_warm_succeeded_count", 0)),
            counters=counters,
            selection_outcome="used_requested_provider" if bool(result.get("total_warm_attempted_count", 0)) else "served_locally",
            served_from="remote_then_persisted" if bool(result.get("total_warm_succeeded_count", 0)) else "none",
            reason_code="remote_fetched" if bool(result.get("total_warm_succeeded_count", 0)) else "local_miss",
            rate_limit_state={"provider_id": "sec", "rate_limited": False, "deferred": False},
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo("m-cache sec monitor loop complete.")


@m_cache_sec_group.group("reconcile")
def m_cache_reconcile_group() -> None:
    """Reconciliation operations."""


@m_cache_reconcile_group.command("run")
@click.pass_context
@click.option("--recent-days", type=click.IntRange(min=0), default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--form-type", "form_types", multiple=True)
@click.option("--form-family", "form_families", type=click.Choice(sorted(FORM_FAMILY_MAP.keys()), case_sensitive=False), multiple=True)
@click.option("--issuer-cik", "issuer_ciks", multiple=True)
@click.option("--catch-up-warm/--no-catch-up-warm", default=False, show_default=True)
@click.option("--refresh-lookup/--no-refresh-lookup", default=True, show_default=True)
@click.option("--summary-json/--no-summary-json", default=True, show_default=True)
@click.option("--progress-json/--no-progress-json", default=True, show_default=True)
@click.option("--progress-heartbeat-seconds", type=click.FloatRange(min=0.0), default=0.0, show_default=True)
def m_cache_reconcile_run(
    ctx: click.Context,
    recent_days: int | None,
    date_from: str | None,
    date_to: str | None,
    form_types: tuple[str, ...],
    form_families: tuple[str, ...],
    issuer_ciks: tuple[str, ...],
    catch_up_warm: bool,
    refresh_lookup: bool,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
) -> None:
    config = _m_cache_runtime_config(ctx)
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="reconcile.run",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema="canonical",
        domain="sec",
        command_path=["m-cache", "sec", "reconcile", "run"],
    )
    with progress:
        result = run_reconciliation(
            config,
            recent_days=recent_days,
            date_from=date_from,
            date_to=date_to,
            form_types=list(form_types) or None,
            form_families=[value.lower() for value in form_families] or None,
            issuer_ciks=list(issuer_ciks) or None,
            catch_up_warm=catch_up_warm,
            refresh_lookup=refresh_lookup,
            progress_callback=(lambda payload: progress.emit_event(**payload)) if machine_progress else None,
        )
        progress.emit_event(
            phase="reconcile.run.result",
            counters={
                "attempted_count": int(result.get("catch_up_attempted_count", 0)),
                "succeeded_count": int(result.get("catch_up_succeeded_count", 0)),
                "failed_count": int(result.get("catch_up_failed_count", 0)),
                "skipped_count": int(result.get("catch_up_skipped_count", 0)),
            },
            provider="sec",
            rate_limit_state="ok",
        )
    if summary_json:
        counters = counters_from_result(
            result,
            key_map={
                "reconciled_row_count": "candidate_count",
                "catch_up_attempted_count": "attempted_count",
                "catch_up_succeeded_count": "succeeded_count",
                "catch_up_failed_count": "failed_count",
                "catch_up_skipped_count": "skipped_count",
            },
        )
        counters["discrepancy_count"] = int(result.get("reconciled_row_count", 0))
        payload = build_canonical_summary(
            status="ok",
            domain="sec",
            command_path=["m-cache", "sec", "reconcile", "run"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=float(result.get("total_elapsed_seconds", 0.0)),
            resolution_mode=None,
            remote_attempted=bool(result.get("catch_up_attempted_count", 0)),
            provider_requested="sec",
            provider_used="sec",
            rate_limited=False,
            retry_count=0,
            persisted_locally=bool(result.get("catch_up_succeeded_count", 0)),
            counters=counters,
            selection_outcome="used_requested_provider" if bool(result.get("catch_up_attempted_count", 0)) else "served_locally",
            served_from="remote_then_persisted" if bool(result.get("catch_up_succeeded_count", 0)) else "none",
            reason_code="reconcile_completed",
            rate_limit_state={"provider_id": "sec", "rate_limited": False, "deferred": False},
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo("m-cache sec reconcile run complete.")


@m_cache_sec_group.group("providers")
def m_cache_providers_group() -> None:
    """Provider inspection operations."""


@m_cache_providers_group.command("list")
@click.pass_context
@click.option("--content-domain", default=None, help="Optional content-domain filter.")
@click.option("--active-only", is_flag=True, default=False, help="Only show active providers.")
@click.option("--provider-type", default=None, help="Optional provider-type filter.")
@click.option("--json/--no-json", "as_json", default=True, show_default=True, help="Emit canonical JSON rows.")
def m_cache_providers_list(
    ctx: click.Context,
    content_domain: str | None,
    active_only: bool,
    provider_type: str | None,
    as_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    rows = list_providers(
        config,
        content_domain=content_domain,
        active_only=active_only,
        provider_type=provider_type,
    )
    if as_json:
        click.echo(json.dumps(rows, sort_keys=True))
        return
    if not rows:
        click.echo("No providers matched.")
        return
    click.echo(pd.DataFrame(rows).to_string(index=False))


@m_cache_providers_group.command("show")
@click.pass_context
@click.option("--provider", "provider_id", required=True, help="Provider identifier.")
@click.option("--json/--no-json", "as_json", default=True, show_default=True, help="Emit canonical JSON detail.")
def m_cache_providers_show(
    ctx: click.Context,
    provider_id: str,
    as_json: bool,
) -> None:
    runtime_config = _m_cache_runtime_config(ctx)
    effective = _m_cache_effective_config(ctx)
    effective_provider = effective_provider_cfg(effective.domains["sec"].providers, provider_id)
    try:
        payload = show_provider(runtime_config, provider_id=provider_id, effective_provider=effective_provider)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(render_summary_block(f"Provider {provider_id}", payload))


@m_cache_sec_group.group("resolve")
def m_cache_resolve_group() -> None:
    """Resolve operations."""


@m_cache_resolve_group.command("filing")
@click.pass_context
@click.option("--accession-number", required=True, help="Canonical SEC accession number (##########-##-######).")
@click.option(
    "--resolution-mode",
    type=click.Choice(["local_only", "resolve_if_missing", "refresh_if_stale"], case_sensitive=False),
    default="resolve_if_missing",
    show_default=True,
)
@click.option("--provider", default="sec", show_default=True, help="Requested provider id.")
@click.option("--summary-json/--no-summary-json", default=True, show_default=True, help="Emit canonical summary JSON to stdout.")
@click.option("--progress-json/--no-progress-json", default=True, show_default=True, help="Emit canonical NDJSON progress events to stderr.")
@click.option("--progress-heartbeat-seconds", type=click.FloatRange(min=0.0), default=0.0, show_default=True)
def m_cache_resolve_filing(
    ctx: click.Context,
    accession_number: str,
    resolution_mode: str,
    provider: str,
    summary_json: bool,
    progress_json: bool,
    progress_heartbeat_seconds: float,
) -> None:
    config = _m_cache_runtime_config(ctx)
    mode = resolution_mode.lower()
    machine_progress = progress_machine_enabled(progress_json=progress_json)
    started_at = utc_now_iso()
    progress = ProgressHeartbeat(
        enabled=machine_progress or progress_enabled(summary_json=summary_json),
        phase="resolve.filing",
        machine_json=machine_progress,
        machine_liveness_seconds=progress_heartbeat_seconds if machine_progress else None,
        output_schema="canonical",
        domain="sec",
        command_path=["m-cache", "sec", "resolve", "filing"],
    )
    with progress:
        service = FilingRetrievalService(config)
        try:
            result = service.retrieve_filing_content_local_first(
                accession_number,
                resolution_mode=mode,
                provider_requested=provider,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        progress.emit_event(
            phase="resolve.filing.result",
            event="progress",
            counters={
                "attempted_count": 1,
                "succeeded_count": 1 if result.success else 0,
                "failed_count": 0 if result.success else 1,
            },
            provider=result.provider_used or result.provider_requested or provider,
            canonical_key=accession_number,
            rate_limit_state="rate_limited" if result.rate_limited else "ok",
        )

    counters = {
        "attempted_count": 1,
        "succeeded_count": 1 if result.success else 0,
        "failed_count": 0 if result.success else 1,
    }
    if summary_json:
        payload = build_canonical_summary(
            status="ok" if result.success else "error",
            domain="sec",
            command_path=["m-cache", "sec", "resolve", "filing"],
            started_at=started_at,
            finished_at=utc_now_iso(),
            elapsed_seconds=0.0,
            resolution_mode=result.resolution_mode,
            remote_attempted=result.remote_attempted,
            provider_requested=result.provider_requested,
            provider_used=result.provider_used,
            rate_limited=result.rate_limited,
            retry_count=result.retry_count,
            persisted_locally=result.persisted_locally,
            counters=counters,
            deferred=bool(result.deferred_until),
            deferred_until=result.deferred_until,
            selection_outcome=result.selection_outcome,
            served_from=result.served_from,
            reason_code=result.reason_code,
            provider_skip_reasons=result.provider_skip_reasons,
            rate_limit_state={
                "provider_id": result.provider_used or result.provider_requested,
                "rate_limited": result.rate_limited,
                "deferred": bool(result.deferred_until),
                "deferred_until": result.deferred_until,
            },
            errors=[] if result.success else [result.error or result.reason or "resolution_failed"],
        )
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(
        render_summary_block(
            f"Resolve filing {accession_number}",
            {
                "resolution_mode": result.resolution_mode,
                "provider_requested": result.provider_requested,
                "provider_used": result.provider_used,
                "served_from": result.served_from,
                "remote_attempted": result.remote_attempted,
                "persisted_locally": result.persisted_locally,
                "success": result.success,
                "reason_code": result.reason_code,
                "rate_limited": result.rate_limited,
                "retry_count": result.retry_count,
                "deferred_until": result.deferred_until,
                "local_path": str(result.local_path) if result.local_path is not None else None,
            },
        )
    )


@m_cache_sec_group.group("storage")
def m_cache_storage_group() -> None:
    """Reserved Wave 1 family (stub)."""


@m_cache_sec_group.group("audit")
def m_cache_audit_group() -> None:
    """Reserved Wave 1 family (stub)."""


@m_cache_sec_group.group("api")
def m_cache_api_group() -> None:
    """Reserved Wave 1 family (stub)."""


@m_cache_sec_group.group("aug")
def m_cache_aug_group() -> None:
    """Canonical augmentation family name."""


@m_cache_sec_group.group("augmentations")
def m_cache_augmentations_alias_group() -> None:
    """Backward-compatible augmentation alias."""


@m_cache_aug_group.command("list-types")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_list_types(as_json: bool) -> None:
    payload = {
        "types": [
            {
                "augmentation_type": shared_type,
                "shared": True,
            }
            for shared_type in SHARED_AUGMENTATION_TYPES
        ]
    }
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    _echo_rows(payload["types"], as_json=False, empty_message="No augmentation types found.")


@m_cache_aug_group.command("inspect-target")
@click.pass_context
@click.option("--accession-number", required=True, help="Canonical filing accession key.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_inspect_target(
    ctx: click.Context,
    accession_number: str,
    as_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    service = FilingRetrievalService(config)
    try:
        metadata = service.find_filing_metadata(accession_number)
        if metadata is None:
            raise click.ClickException(
                "Filing metadata was not found in local lookup or merged index metadata."
            )
        meta = build_api_augmentation_meta(config, accession_number)
        rows = service.list_augmentations_for_accession(accession_number, limit=200)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    canonical_types_present = sorted(
        {
            mapped
            for mapped in [
                map_to_shared_augmentation_type(
                    augmentation_type=str(row.get("augmentation_type") or ""),
                    layer_type=str(row.get("layer_type") or ""),
                )
                for row in rows
            ]
            if mapped is not None
        }
    )
    payload = {
        "domain": "sec",
        "resource_family": "filing",
        "canonical_key": accession_number,
        "augmentation_meta": meta,
        "target_descriptor": meta.get("target_descriptor"),
        "source_text_version": meta.get("source_text_version"),
        "canonical_types_present": canonical_types_present,
        "run_count": len(rows),
        "inspect_path": meta.get("inspect_path"),
    }
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(render_summary_block(f"Inspect target {accession_number}", payload))


@m_cache_aug_group.command("submit-run")
@click.option("--payload-json", default=None, help="Inline run-submission JSON envelope.")
@click.option(
    "--payload-file",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False),
    default=None,
    help="Path to run-submission JSON envelope.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_submit_run(
    payload_json: str | None,
    payload_file: Path | None,
    as_json: bool,
) -> None:
    payload = _load_aug_payload_or_fail(payload_json=payload_json, payload_file=payload_file)
    try:
        validated = validate_producer_run_submission(payload)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    result = {
        "accepted": False,
        "validated": True,
        "command": "submit-run",
        "mode": "validate_only",
        "non_pilot": True,
        "persisted": False,
        "message": "Wave 4.1 non-pilot surface: envelope validated, no write-path executed.",
        "run": validated,
    }
    if as_json:
        click.echo(json.dumps(result, sort_keys=True))
        return
    click.echo(render_summary_block("Submit run (validate-only)", result))


@m_cache_aug_group.command("submit-artifact")
@click.option("--payload-json", default=None, help="Inline artifact-submission JSON envelope.")
@click.option(
    "--payload-file",
    type=click.Path(path_type=Path, file_okay=True, dir_okay=False),
    default=None,
    help="Path to artifact-submission JSON envelope.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_submit_artifact(
    payload_json: str | None,
    payload_file: Path | None,
    as_json: bool,
) -> None:
    payload = _load_aug_payload_or_fail(payload_json=payload_json, payload_file=payload_file)
    try:
        validated = validate_producer_artifact_submission(payload)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    result = {
        "accepted": False,
        "validated": True,
        "command": "submit-artifact",
        "mode": "validate_only",
        "non_pilot": True,
        "persisted": False,
        "message": "Wave 4.1 non-pilot surface: envelope validated, no write-path executed.",
        "artifact": validated,
    }
    if as_json:
        click.echo(json.dumps(result, sort_keys=True))
        return
    click.echo(render_summary_block("Submit artifact (validate-only)", result))


@m_cache_aug_group.command("status")
@click.pass_context
@click.option("--run-id", default=None, help="Canonical run id.")
@click.option(
    "--idempotency-key",
    default=None,
    help="Optional producer idempotency key. When explicit key storage is absent, run_id-compatible values are accepted.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_status(
    ctx: click.Context,
    run_id: str | None,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    if not run_id and not idempotency_key:
        raise click.ClickException("Provide --run-id or --idempotency-key.")
    config = _m_cache_runtime_config(ctx)
    materialize_shared_augmentation_metadata(config)
    runs = load_shared_augmentation_runs(config)
    if runs.empty:
        raise click.ClickException("No augmentation runs found.")

    selected: pd.DataFrame
    if run_id:
        selected = runs[runs["run_id"].astype(str) == str(run_id)]
    elif "idempotency_key" in runs.columns:
        selected = runs[runs["idempotency_key"].astype(str) == str(idempotency_key)]
    else:
        selected = runs[runs["run_id"].astype(str) == str(idempotency_key)]

    if selected.empty:
        raise click.ClickException("Run status not found for provided selector.")
    row = selected.iloc[0].to_dict()
    canonical_key = str(row.get("canonical_key") or "")
    current_version = deterministic_source_text_version(config, canonical_key) if canonical_key else None
    source_text_version = str(row.get("source_text_version") or "") or None
    status_row = build_run_status_view(
        run_id=str(row.get("run_id") or ""),
        idempotency_key=(
            str(row.get("idempotency_key"))
            if "idempotency_key" in selected.columns and pd.notna(row.get("idempotency_key"))
            else str(idempotency_key or row.get("run_id") or "")
        ),
        augmentation_type=str(row.get("augmentation_type") or ""),
        canonical_key=canonical_key,
        source_text_version=str(source_text_version or ""),
        producer_name=str(row.get("producer_name") or ""),
        producer_version=str(row.get("producer_version") or ""),
        status=str(row.get("status") or ""),
        success=bool(row.get("success")),
        reason_code=str(row.get("reason_code") or ""),
        persisted_locally=bool(row.get("persisted_locally")),
        augmentation_stale=(
            bool(source_text_version != current_version)
            if source_text_version is not None and current_version is not None
            else None
        ),
        last_updated_at=str(row.get("event_at") or "") or None,
    )
    payload = {"status": status_row}
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
        return
    click.echo(render_summary_block(f"Run status {status_row['run_id']}", status_row))


@m_cache_aug_group.command("inspect-runs")
@click.pass_context
@click.option("--accession-number", default=None, help="Optional canonical filing accession key filter.")
@click.option("--submission-id", default=None, help="Optional SEC submission id filter.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_inspect_runs(
    ctx: click.Context,
    accession_number: str | None,
    submission_id: str | None,
    limit: int,
    as_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    materialize_shared_augmentation_metadata(config)
    runs = load_shared_augmentation_runs(config)
    if accession_number:
        runs = runs[runs["canonical_key"].astype(str) == str(accession_number)]
    if submission_id:
        runs = runs[runs["source_submission_id"].astype(str) == str(submission_id)]
    runs = runs.head(int(limit)).reset_index(drop=True)
    rows = runs.to_dict(orient="records")
    if as_json:
        click.echo(json.dumps({"runs": rows}, sort_keys=True))
        return
    _echo_rows(rows, as_json=False, empty_message="No augmentation runs found.")


@m_cache_aug_group.command("inspect-artifacts")
@click.pass_context
@click.option("--accession-number", default=None, help="Optional canonical filing accession key filter.")
@click.option("--submission-id", default=None, help="Optional SEC submission id filter.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_inspect_artifacts(
    ctx: click.Context,
    accession_number: str | None,
    submission_id: str | None,
    limit: int,
    as_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    rows = list_shared_augmentation_artifacts(
        config,
        accession_number=accession_number,
        submission_id=submission_id,
        limit=limit,
    )
    if as_json:
        click.echo(json.dumps({"artifacts": rows}, sort_keys=True))
        return
    _echo_rows(rows, as_json=False, empty_message="No augmentation artifacts found.")


@m_cache_aug_group.command("events")
@click.pass_context
@click.option("--accession-number", default=None, help="Optional canonical filing accession key filter.")
@click.option("--submission-id", default=None, help="Optional SEC submission id filter.")
@click.option("--limit", type=click.IntRange(min=0), default=100, show_default=True, help="Maximum rows to print.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON payload only.")
def m_cache_aug_events(
    ctx: click.Context,
    accession_number: str | None,
    submission_id: str | None,
    limit: int,
    as_json: bool,
) -> None:
    config = _m_cache_runtime_config(ctx)
    materialize_shared_augmentation_metadata(config)
    rows = load_shared_augmentation_events(config)
    if accession_number:
        rows = rows[rows["canonical_key"].astype(str) == str(accession_number)]
    if submission_id:
        rows = rows[rows["source_submission_id"].astype(str) == str(submission_id)]
    rows = rows.head(int(limit)).reset_index(drop=True)
    payload_rows = rows.to_dict(orient="records")
    if as_json:
        click.echo(json.dumps({"events": payload_rows}, sort_keys=True))
        return
    _echo_rows(payload_rows, as_json=False, empty_message="No augmentation events found.")


for _m_cache_aug_name, _m_cache_aug_command in augmentations_group.commands.items():
    if _m_cache_aug_name not in m_cache_aug_group.commands:
        m_cache_aug_group.add_command(_m_cache_aug_command, _m_cache_aug_name)
    m_cache_augmentations_alias_group.add_command(_m_cache_aug_command, _m_cache_aug_name)

for _m_cache_aug_name, _m_cache_aug_command in m_cache_aug_group.commands.items():
    if _m_cache_aug_name not in m_cache_augmentations_alias_group.commands:
        m_cache_augmentations_alias_group.add_command(_m_cache_aug_command, _m_cache_aug_name)


if __name__ == "__main__":
    main()
