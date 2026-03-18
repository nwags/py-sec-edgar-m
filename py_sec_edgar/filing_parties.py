from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from py_sec_edgar.refdata.normalize import normalize_cik


FILING_PARTY_COLUMNS = [
    "accession_number",
    "form_type",
    "filing_date",
    "party_role",
    "party_cik",
    "party_name",
    "issuer_cik",
    "issuer_name",
    "source",
    "source_filename",
]

FILING_PARTY_DEDUPE_KEYS = [
    "accession_number",
    "party_role",
    "party_cik",
    "party_name",
    "source_filename",
]

SUPPORTED_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "3", "4", "5"}

_SECTION_MARKERS = {
    "SUBJECT COMPANY:": "subject_company",
    "FILED BY:": "filed_by",
}


def _normalize_form_type(form_type: str | None) -> str:
    return str(form_type or "").strip().upper()


def _accession_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    base = Path(str(filename)).name
    if base.lower().endswith(".txt"):
        base = base[:-4]
    return base or None


def _extract_header_text(raw_text: str) -> str:
    match = re.search(r"<(SEC-HEADER|sec-header)>(.*?)</(SEC-HEADER|sec-header)>", raw_text, flags=re.DOTALL)
    if match:
        return match.group(2)
    return raw_text


def _extract_sections(header_text: str) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = {"subject_company": [], "filed_by": []}
    current: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current, current_lines
        if current and current_lines:
            sections[current].append(current_lines)
        current = None
        current_lines = []

    for line in header_text.splitlines():
        clean = str(line).strip()
        if not clean:
            continue
        marker = _SECTION_MARKERS.get(clean.upper())
        if marker:
            flush()
            current = marker
            continue
        if current:
            upper = clean.upper()
            # End current section at a new all-caps labeled section marker.
            if upper.endswith(":") and upper == clean and len(upper) < 80:
                flush()
                continue
            current_lines.append(clean)

    flush()
    return sections


def _parse_name_cik(section_lines: list[str]) -> tuple[str | None, str | None]:
    name = None
    cik = None
    for line in section_lines:
        upper = line.upper()
        if "COMPANY CONFORMED NAME:" in upper:
            name = line.split(":", 1)[1].strip() if ":" in line else None
        elif "CENTRAL INDEX KEY:" in upper:
            raw = line.split(":", 1)[1].strip() if ":" in line else None
            cik = normalize_cik(raw)
    return name, cik


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _find_child_text(node: ET.Element, child_name: str) -> str | None:
    for child in list(node):
        if _local_name(child.tag) == child_name:
            text = (child.text or "").strip()
            return text or None
    return None


def _find_descendant(node: ET.Element, name: str) -> ET.Element | None:
    for elem in node.iter():
        if _local_name(elem.tag) == name:
            return elem
    return None


def _is_true(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "y", "yes"}


def _ownership_document_root(raw_text: str) -> ET.Element | None:
    xml_chunks = re.findall(r"<XML>(.*?)</XML>", raw_text, flags=re.DOTALL | re.IGNORECASE)
    candidates = xml_chunks if xml_chunks else [raw_text]
    for chunk in candidates:
        text = chunk.strip()
        if not text:
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        if _local_name(root.tag) == "ownershipDocument" or _find_descendant(root, "ownershipDocument") is not None:
            if _local_name(root.tag) == "ownershipDocument":
                return root
            return _find_descendant(root, "ownershipDocument")
    return None


def _extract_ownership_form_records(
    *,
    raw_text: str,
    normalized_form: str,
    filing_date: str | None,
    source_filename: str | None,
    source: str,
) -> list[dict[str, Any]]:
    root = _ownership_document_root(raw_text)
    if root is None:
        return []

    accession_number = _accession_from_filename(source_filename)

    issuer_node = _find_descendant(root, "issuer")
    issuer_name = _find_child_text(issuer_node, "issuerName") if issuer_node is not None else None
    issuer_cik = normalize_cik(_find_child_text(issuer_node, "issuerCik")) if issuer_node is not None else None

    records: list[dict[str, Any]] = []
    if issuer_name or issuer_cik:
        records.append(
            {
                "accession_number": accession_number,
                "form_type": normalized_form,
                "filing_date": filing_date,
                "party_role": "issuer",
                "party_cik": issuer_cik,
                "party_name": issuer_name,
                "issuer_cik": issuer_cik,
                "issuer_name": issuer_name,
                "source": source,
                "source_filename": source_filename,
            }
        )

    for owner in root.iter():
        if _local_name(owner.tag) != "reportingOwner":
            continue

        owner_id = _find_descendant(owner, "reportingOwnerId")
        rel = _find_descendant(owner, "reportingOwnerRelationship")
        party_name = _find_child_text(owner_id, "rptOwnerName") if owner_id is not None else None
        party_cik = normalize_cik(_find_child_text(owner_id, "rptOwnerCik")) if owner_id is not None else None
        if not party_name and not party_cik:
            continue

        base_record = {
            "accession_number": accession_number,
            "form_type": normalized_form,
            "filing_date": filing_date,
            "party_cik": party_cik,
            "party_name": party_name,
            "issuer_cik": issuer_cik,
            "issuer_name": issuer_name,
            "source": source,
            "source_filename": source_filename,
        }

        records.append({**base_record, "party_role": "reporting_owner"})

        if rel is not None and _is_true(_find_child_text(rel, "isDirector")):
            records.append({**base_record, "party_role": "director"})
        if rel is not None and _is_true(_find_child_text(rel, "isOfficer")):
            records.append({**base_record, "party_role": "officer"})
        if rel is not None and _is_true(_find_child_text(rel, "isTenPercentOwner")):
            records.append({**base_record, "party_role": "ten_percent_owner"})

    return records


def extract_filing_parties_from_text(
    *,
    raw_text: str,
    form_type: str | None,
    filing_date: str | None = None,
    source_filename: str | None = None,
    source: str = "sec_header",
) -> list[dict[str, Any]]:
    normalized_form = _normalize_form_type(form_type)
    if normalized_form not in SUPPORTED_FORMS:
        return []

    if normalized_form in {"3", "4", "5"}:
        records = _extract_ownership_form_records(
            raw_text=raw_text,
            normalized_form=normalized_form,
            filing_date=filing_date,
            source_filename=source_filename,
            source=source,
        )
    else:
        header_text = _extract_header_text(raw_text)
        sections = _extract_sections(header_text)

        issuer_name = None
        issuer_cik = None
        records = []
        accession_number = _accession_from_filename(source_filename)

        for section_lines in sections.get("subject_company", []):
            name, cik = _parse_name_cik(section_lines)
            if not name and not cik:
                continue
            issuer_name = issuer_name or name
            issuer_cik = issuer_cik or cik
            records.append(
                {
                    "accession_number": accession_number,
                    "form_type": normalized_form,
                    "filing_date": filing_date,
                    "party_role": "subject_company",
                    "party_cik": cik,
                    "party_name": name,
                    "issuer_cik": issuer_cik,
                    "issuer_name": issuer_name,
                    "source": source,
                    "source_filename": source_filename,
                }
            )

        if issuer_name or issuer_cik:
            records.append(
                {
                    "accession_number": accession_number,
                    "form_type": normalized_form,
                    "filing_date": filing_date,
                    "party_role": "issuer",
                    "party_cik": issuer_cik,
                    "party_name": issuer_name,
                    "issuer_cik": issuer_cik,
                    "issuer_name": issuer_name,
                    "source": source,
                    "source_filename": source_filename,
                }
            )

        for section_lines in sections.get("filed_by", []):
            name, cik = _parse_name_cik(section_lines)
            if not name and not cik:
                continue
            records.append(
                {
                    "accession_number": accession_number,
                    "form_type": normalized_form,
                    "filing_date": filing_date,
                    "party_role": "reporting_owner",
                    "party_cik": cik,
                    "party_name": name,
                    "issuer_cik": issuer_cik,
                    "issuer_name": issuer_name,
                    "source": source,
                    "source_filename": source_filename,
                }
            )

    deduped = []
    seen = set()
    for record in records:
        key = (
            record.get("accession_number"),
            record.get("party_role"),
            record.get("party_cik"),
            record.get("party_name"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def extract_filing_parties_from_file(
    *,
    filing_filepath: str | Path,
    form_type: str | None,
    filing_date: str | None = None,
    source_filename: str | None = None,
) -> list[dict[str, Any]]:
    path = Path(filing_filepath)
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    return extract_filing_parties_from_text(
        raw_text=raw_text,
        form_type=form_type,
        filing_date=filing_date,
        source_filename=source_filename,
    )


def _records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for column in FILING_PARTY_COLUMNS:
        if column not in df.columns:
            df[column] = None
    df = df[FILING_PARTY_COLUMNS]
    # Normalize common text fields for deterministic dedupe and stable output.
    for column in ["accession_number", "party_role", "party_name", "source", "source_filename", "issuer_name"]:
        df[column] = df[column].map(lambda v: str(v).strip() if v is not None else None)
    df["party_cik"] = df["party_cik"].map(normalize_cik)
    df["issuer_cik"] = df["issuer_cik"].map(normalize_cik)
    return df


def upsert_filing_parties_parquet(
    *,
    records: list[dict[str, Any]],
    output_path: str | Path,
) -> int:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    new_df = _records_to_dataframe(records)
    if new_df.empty and not target.exists():
        return 0

    if target.exists():
        existing_df = pd.read_parquet(target)
        existing_df = _records_to_dataframe(existing_df.to_dict(orient="records"))
    else:
        existing_df = pd.DataFrame(columns=FILING_PARTY_COLUMNS)

    existing_df = existing_df.drop_duplicates(subset=FILING_PARTY_DEDUPE_KEYS, keep="last")
    before_count = int(len(existing_df.index))

    merged = pd.concat([existing_df, new_df], ignore_index=True, sort=False)
    merged = merged.drop_duplicates(subset=FILING_PARTY_DEDUPE_KEYS, keep="last")
    merged = merged.sort_values(FILING_PARTY_DEDUPE_KEYS, na_position="last").reset_index(drop=True)
    merged.to_parquet(target, index=False)

    after_count = int(len(merged.index))
    return max(0, after_count - before_count)
