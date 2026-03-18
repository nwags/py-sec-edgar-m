from __future__ import annotations

import json
from pathlib import Path

import click

from py_sec_edgar.config import load_config
from py_sec_edgar.filters import FORM_FAMILY_MAP
from py_sec_edgar.filing_parties_query import (
    apply_limit_and_columns,
    load_filing_parties_parquet,
    parse_columns_option,
    query_filing_parties,
)
from py_sec_edgar.pipelines.backfill import run_backfill
from py_sec_edgar.pipelines.index_refresh import run_index_refresh
from py_sec_edgar.pipelines.refdata_refresh import run_refdata_refresh


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
def refdata_refresh(project_root: Path | None) -> None:
    config = load_config(project_root)
    written = run_refdata_refresh(config)
    click.echo("Refdata refresh complete:")
    for name, out_path in sorted(written.items()):
        click.echo(f"- {name}: {out_path}")


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
def index_refresh(skip_if_exists: bool, save_idx_as_csv: bool) -> None:
    config = load_config()
    run_index_refresh(
        config,
        save_idx_as_csv=save_idx_as_csv,
        skip_if_exists=skip_if_exists,
    )
    click.echo("Index refresh complete.")


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


@main.command("backfill")
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
def backfill(
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
) -> None:
    config = load_config()
    try:
        result = run_backfill(
            config,
            refresh_index=refresh_index,
            execute_downloads=execute_downloads,
            execute_extraction=execute_extraction,
            persist_filing_parties=persist_filing_parties,
            ticker_list_filter=ticker_list_filter,
            form_list_filter=form_list_filter,
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
    if summary_json:
        click.echo(json.dumps(result, sort_keys=True))
        return

    click.echo("Backfill candidate load complete.")
    click.echo(f"- candidate_count: {result['candidate_count']}")
    click.echo(f"- download_attempted_count: {result['download_attempted_count']}")
    click.echo(f"- download_succeeded_count: {result['download_succeeded_count']}")
    click.echo(f"- download_failed_count: {result['download_failed_count']}")
    click.echo(f"- extraction_attempted_count: {result['extraction_attempted_count']}")
    click.echo(f"- extraction_succeeded_count: {result['extraction_succeeded_count']}")
    click.echo(f"- extraction_failed_count: {result['extraction_failed_count']}")
    click.echo(f"- filing_party_record_count: {result['filing_party_record_count']}")
    click.echo(f"- filing_party_persisted_count: {result['filing_party_persisted_count']}")
    persist_path = result.get("filing_party_persist_path")
    if persist_path:
        click.echo(f"- filing_party_persist_path: {persist_path}")


if __name__ == "__main__":
    main()
