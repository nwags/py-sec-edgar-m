from __future__ import annotations

from py_sec_edgar.sec_surfaces import default_sec_surfaces, sec_surfaces_dataframe


def test_sec_surface_registry_has_required_fields_and_deterministic_priority() -> None:
    surfaces = default_sec_surfaces()
    assert surfaces
    priorities = [item.retrieval_priority for item in surfaces]
    assert priorities == sorted(priorities)

    ids = {item.surface_id for item in surfaces}
    assert "sec_archives_full_index" in ids
    assert "sec_archives_daily_index" in ids
    assert "sec_feed_current_atom" in ids
    assert "sec_archives_submissions" in ids


def test_sec_surfaces_dataframe_contains_expected_columns() -> None:
    df = sec_surfaces_dataframe()
    required = {
        "provider_id",
        "provider_type",
        "surface_id",
        "surface_name",
        "base_url",
        "auth_model",
        "supports_historical_discovery",
        "supports_recent_discovery",
        "supports_metadata_resolution",
        "supports_content_retrieval",
        "content_fetch_canonical",
        "metadata_only",
        "retrieval_priority",
        "rate_limit_notes",
        "fair_access_notes",
        "operational_caveats",
    }
    assert required.issubset(set(df.columns))
    archives_row = df[df["surface_id"] == "sec_archives_submissions"].iloc[0]
    assert bool(archives_row["supports_content_retrieval"]) is True
    assert bool(archives_row["content_fetch_canonical"]) is True
