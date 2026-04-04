from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd


SEC_PROVIDER_ID = "sec"
SEC_PROVIDER_TYPE = "official_regulator"


@dataclass(frozen=True)
class SecSurface:
    provider_id: str
    provider_type: str
    surface_id: str
    surface_name: str
    base_url: str
    auth_model: str
    supports_historical_discovery: bool
    supports_recent_discovery: bool
    supports_metadata_resolution: bool
    supports_content_retrieval: bool
    content_fetch_canonical: bool
    metadata_only: bool
    retrieval_priority: int
    rate_limit_notes: str
    fair_access_notes: str
    operational_caveats: str


def default_sec_surfaces() -> list[SecSurface]:
    return [
        SecSurface(
            provider_id=SEC_PROVIDER_ID,
            provider_type=SEC_PROVIDER_TYPE,
            surface_id="sec_archives_full_index",
            surface_name="SEC EDGAR Full Index",
            base_url="https://www.sec.gov/Archives/edgar/full-index/",
            auth_model="none",
            supports_historical_discovery=True,
            supports_recent_discovery=False,
            supports_metadata_resolution=True,
            supports_content_retrieval=False,
            content_fetch_canonical=False,
            metadata_only=True,
            retrieval_priority=10,
            rate_limit_notes="Use shared process-wide request budget and persistent sessions.",
            fair_access_notes="Identify requester with declared User-Agent and stay below configured global request budget.",
            operational_caveats="Primary historical discovery surface. Use with daily index and feed for freshness coverage.",
        ),
        SecSurface(
            provider_id=SEC_PROVIDER_ID,
            provider_type=SEC_PROVIDER_TYPE,
            surface_id="sec_archives_daily_index",
            surface_name="SEC EDGAR Daily Index",
            base_url="https://www.sec.gov/Archives/edgar/daily-index/",
            auth_model="none",
            supports_historical_discovery=True,
            supports_recent_discovery=True,
            supports_metadata_resolution=True,
            supports_content_retrieval=False,
            content_fetch_canonical=False,
            metadata_only=True,
            retrieval_priority=20,
            rate_limit_notes="Use shared process-wide request budget and persistent sessions.",
            fair_access_notes="Identify requester with declared User-Agent and stay below configured global request budget.",
            operational_caveats="Useful for incremental refresh windows; merged with full index artifacts locally.",
        ),
        SecSurface(
            provider_id=SEC_PROVIDER_ID,
            provider_type=SEC_PROVIDER_TYPE,
            surface_id="sec_feed_current_atom",
            surface_name="SEC Current Feed (ATOM)",
            base_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&count=100&output=atom",
            auth_model="none",
            supports_historical_discovery=False,
            supports_recent_discovery=True,
            supports_metadata_resolution=True,
            supports_content_retrieval=False,
            content_fetch_canonical=False,
            metadata_only=True,
            retrieval_priority=30,
            rate_limit_notes="Use shared process-wide request budget and persistent sessions.",
            fair_access_notes="Identify requester with declared User-Agent and stay below configured global request budget.",
            operational_caveats="Freshness-oriented signal surface; entries may require canonical filename normalization.",
        ),
        SecSurface(
            provider_id=SEC_PROVIDER_ID,
            provider_type=SEC_PROVIDER_TYPE,
            surface_id="sec_archives_submissions",
            surface_name="SEC Archives Raw Submission Text",
            base_url="https://www.sec.gov/Archives/",
            auth_model="none",
            supports_historical_discovery=False,
            supports_recent_discovery=False,
            supports_metadata_resolution=False,
            supports_content_retrieval=True,
            content_fetch_canonical=True,
            metadata_only=False,
            retrieval_priority=40,
            rate_limit_notes="Use shared process-wide request budget and persistent sessions.",
            fair_access_notes="Identify requester with declared User-Agent and stay below configured global request budget.",
            operational_caveats="Canonical content retrieval surface for accession-resolved submission filenames.",
        ),
        SecSurface(
            provider_id=SEC_PROVIDER_ID,
            provider_type=SEC_PROVIDER_TYPE,
            surface_id="sec_data_submissions_api",
            surface_name="SEC submissions API",
            base_url="https://data.sec.gov/submissions/",
            auth_model="none",
            supports_historical_discovery=False,
            supports_recent_discovery=True,
            supports_metadata_resolution=True,
            supports_content_retrieval=False,
            content_fetch_canonical=False,
            metadata_only=True,
            retrieval_priority=50,
            rate_limit_notes="Use shared process-wide request budget and persistent sessions.",
            fair_access_notes="Identify requester with declared User-Agent and stay below configured global request budget.",
            operational_caveats="Metadata/API surface. Does not replace archive submission content retrieval.",
        ),
    ]


def sec_surfaces_dataframe() -> pd.DataFrame:
    rows = [asdict(item) for item in default_sec_surfaces()]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=list(SecSurface.__annotations__.keys()))
    return df.sort_values(["provider_id", "retrieval_priority", "surface_id"], ascending=[True, True, True]).reset_index(drop=True)
