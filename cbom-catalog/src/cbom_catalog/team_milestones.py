"""Reviewed, immutable Team Tracker enrichment for FIPS candidate views.

This module deliberately keeps tracker commitments separate from assessment
evidence.  A tracker row is planning metadata, never proof of CMVP validation
or a FedRAMP compliance conclusion.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any


TRACKER_SOURCE = {
    "source": "FIPS 140-3 Engineering Milestone Tracker attached Confluence export",
    "url": "https://cisco-sbg.atlassian.net/wiki/spaces/PROD/pages/1492947409/FIPS+140-3+Engineering+Milestone+Tracker#Team-Tracker",
    "page_id": "1492947409",
    "source_file": "FIPS+140-3+Engineering+Milestone+Tracker.doc",
    "source_file_sha256": "88079a7b6ea1659effe45637dce850e2e8eeba6a15df718c68c70ff3a439ed62",
    "table_rows": 40,
    "table_columns": 16,
    "observed_at": "2026-09-18T07:56:53Z",
    "mapping_reviewed_at": "2026-09-18",
    "mapping_status": "repopulated from user-supplied authoritative export",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


# Only fields required for portfolio routing are copied here. Raw milestone
# cells preserve the attached export's date and qualifying text for auditability.
_TEAM_ROWS: dict[str, dict[str, Any]] = {
    "APIX": {"team": "APIX (Authsvc,APIGW)", "owner": "Prashanth", "lead": "Pankaja Dakhane", "il2": "13 Nov 2026 (KONG version upgrade drives this date, other tickets would come sooner.)", "il5": "20 Nov 2026 (KONG version upgrade drives this date, other tickets would come sooner.)"},
    "SFCN-RAVPN": {"team": "SFCN RAVPN", "owner": "Ashok", "lead": "RA-VPN - Anurag Shukla / ASA - Narendra Meka", "il2": "18 Nov 2026 (Deployment to be done based on the availability of SRE team.)", "il5": "18 Nov 2026"},
    "ZTA-BAP": {"team": "ZTA BAP", "owner": "John", "lead": "Arun Babu Chandrababu / Amit Kumar", "il2": "22 Sep 2026", "il5": ""},
    "ZTA-CLAP": {"team": "ZTA CLAP", "owner": "John", "lead": "Arun Babu Chandrababu / Amit Kumar", "il2": "22 Sep 2026 + 1w lead time", "il5": ""},
    "BRAIN": {"team": "Brain", "owner": "Prashanth", "lead": "Ashutosh Saxena", "il2": "06 Nov 2026", "il5": ""},
    "DATA-PLATFORM": {"team": "DP (Data Platform)", "owner": "Prashanth", "lead": "Ashutosh Saxena", "il2": "04 Dec 2026", "il5": ""},
    "METERING": {"team": "Metering", "owner": "Prashanth", "lead": "Ashutosh Saxena", "il2": "06 Nov 2026", "il5": ""},
    "REPORTING": {"team": "Reporting", "owner": "Prashanth", "lead": "Ashutosh Saxena", "il2": "04 Dec 2026", "il5": ""},
    "UNIFIED-POLICY": {"team": "UP (Unified Policy)", "owner": "Prashanth", "lead": "Ashutosh Saxena", "il2": "06 Nov 2026", "il5": ""},
    "SWG-PROXY": {"team": "SWG Proxy", "owner": "Avnish", "lead": "Dinesh Upreti", "il2": "Next week Wave - CRs…", "il5": ""},
    "OPC": {"team": "OPC", "owner": "Avnish", "lead": "Dinesh Upreti / Preet Kumar Sahu", "il2": "", "il5": ""},
    "DNS-PLATFORM": {"team": "DNS (Resolver)", "owner": "Ashok", "lead": "Dipa Thakkar / Prashanth Suvarna", "il2": "26 Feb 2027", "il5": "26 Feb 2027"},
    "DISTHOST": {"team": "DistHost", "owner": "Avnish", "lead": "Georgekutty Jose", "il2": "30 Sep 2026 / Fedramp Cycle", "il5": "30 Sep 2026"},
    "DOWNLOAD-SERVICE": {"team": "Download Service", "owner": "Avnish", "lead": "Georgekutty Jose", "il2": "22 Sep 2026 / Fedramp Cycle", "il5": "22 Sep 2026"},
    "LANDERS": {"team": "Landers", "owner": "Avnish", "lead": "Georgekutty Jose", "il2": "", "il5": "NA"},
    "CONTRAAST": {"team": "ContraaST", "owner": "John", "lead": "Pallavi Priya", "il2": "", "il5": ""},
    "KNEX": {"team": "KNEX", "owner": "John", "lead": "Pallavi Priya", "il2": "", "il5": ""},
    "PAC-CSC-OVD-TIG": {"team": "PAC/CSC/OVD/TIG", "owner": "Avnish", "lead": "Udhandaraman Velayutham", "il2": "17sept", "il5": "17sept"},
    "SCC": {"team": "SCC", "owner": "", "lead": "Naveen Benagi, Mohammad Islam", "il2": "31 Oct 2026", "il5": "31 Oct 2026"},
    "SCC-BACKEND": {"team": "SCC -Backend Services (Feature Service, Self-service, Platform Notification Service, SCG Service)", "owner": "Mohammad Islam", "lead": "Amar Lal Dhakad", "il2": "", "il5": ""},
    "DISCOVERY": {"team": "Discovery", "owner": "", "lead": "Satyasanjibani Routray", "il2": "11 Oct 2026", "il5": ""},
    "RESOURCE-DISCOVERY": {"team": "Resource Discovery", "owner": "Ashok", "lead": "Rakesh Muthusamy", "il2": "", "il5": ""},
    "FRUP-MICROAPPS": {"team": "FRUP / MicroApps | DAPI", "owner": "Avnish", "lead": "Ananth (Muruganantham) Dhanapal / Tarun Juneja", "il2": "12 Oct 2026", "il5": "12 Oct 2026"},
    "SAASAPI": {"team": "SaaS API", "owner": "Avnish", "lead": "Prabha Loganayaki", "il2": "25 Sep 2026", "il5": "25 Sep 2026"},
    "IDENTITY-CORE": {"team": "Identity Core", "owner": "John", "lead": "Arindam Gupta / Sameer Bansal", "il2": "18 Sep 2026", "il5": "17 Sep 2026"},
    "IDENTITY-APPS": {"team": "Identity Apps", "owner": "John", "lead": "Arindam Gupta / Sameer Bansal", "il2": "18 Sep 2026", "il5": "17 Sep 2026"},
    "DLP": {"team": "DLP", "owner": "Avnish", "lead": "Smitha Sushil", "il2": "24 Sep 2026", "il5": "24 Sep 2026"},
    "FIS-SMA-THREATGRID": {"team": "FIS/SMA Threatgrid", "owner": "Avnish", "lead": "Smitha Sushil", "il2": "24 Sep 2026", "il5": "24 Sep 2026"},
    "SFCN-FIREWALL": {"team": "SFCN Firewall", "owner": "Ashok", "lead": "PravinKumar Parsa", "il2": "04 Dec 2026", "il5": "15 Dec 2026"},
    "CNHE": {"team": "CNHE", "owner": "Ashok", "lead": "Ravinder Narula / Vimal Vijayvargia", "il2": "8-Nov-2026", "il5": "15-Nov-2026"},
    "DW-VOLT": {"team": "DW/VOLT", "owner": "Prashanth", "lead": "Doug Tabacco", "il2": "10/13/2026", "il5": "10/20/2026"},
    "OVD-APP-DISCOVERY": {"team": "OVD- APP-Discovery", "owner": "Avnish", "lead": "Udhandaraman Velayutham", "il2": "30th SEPT", "il5": "30th SEPT"},
    "VA": {"team": "VA", "owner": "Avnish", "lead": "Sandeep Kumar T.K.", "il2": "March 2027", "il5": "March 2027"},
    "ANDROID": {"team": "Android", "owner": "Avnish", "lead": "Dinesh Upreti / Amarnath Jiyawan", "il2": "NA (Play Store)", "il5": "NA (Play Store)"},
    "FROUTER": {"team": "Frouter", "owner": "Ashok", "lead": "Joel Ahn", "il2": "", "il5": ""},
    "ON-PREM-CLIENTS": {"team": "On Prem/Clients", "owner": "", "lead": "", "il2": "", "il5": ""},
    "ADC": {"team": "ADC", "owner": "Avnish", "lead": "Sandeep Kumar T. K.", "il2": "15 Jan 2027", "il5": "15 Jan 2027"},
    "SWG-ROAMING-CLIENT": {"team": "Roaming SWG Client", "owner": "Avnish", "lead": "Dinesh Upreti / Sriraksha Shantharam", "il2": "", "il5": ""},
    "RSM-SECURE-CLIENT": {"team": "RSM/Secure Client", "owner": "John", "lead": "Erik Peterson", "il2": "", "il5": ""},
    "IOS": {"team": "iOS", "owner": "John", "lead": "Erik Peterson", "il2": "", "il5": ""},
}

# Exact CMVP-mapping cells (or, for OPC/SWG Proxy, the directly associated
# tracker comment) retained from the attached 2026-09-18 export.  These are
# provider-attributed planning assertions, not independent CMVP verification.
_CMVP_MAPPING_BY_TEAM: dict[str, str] = {
    "SFCN-RAVPN": "OpenSSL: 3.1.2; Golang with native cryptography",
    "SWG-PROXY": "OpenSSL 3.5.x — tracker comment identifies CMVP In-Test",
    "OPC": "FOM 7.3a — tracker reports NIST FIPS 140-3 certificate #4747 valid through 2029-07-31",
    "DNS-PLATFORM": "OpenSSL certificate #4282 (FIPS 140-2)",
    "DISTHOST": "Active",
    "DOWNLOAD-SERVICE": "Active",
    "LANDERS": "Testing — OpenSSL 3.5.x submission",
    "DW-VOLT": "OpenSSL FIPS Provider 3.1.2, NIST certificate #4985 / Cisco provider #5160, active through 2030-03-10",
    "SAASAPI": "TBD",
    "IDENTITY-CORE": "TBD",
    "IDENTITY-APPS": "TBD",
    "DISCOVERY": "Targeting HashiCorp FIPS 140-3 enterprise compliance image",
    "DLP": "OpenSSL #4282 legacy; BouncyCastle #3514; OpenSSL 3.1.2 certificate #4985 Active",
    "FIS-SMA-THREATGRID": "OpenSSL #4282 and BouncyCastle #3514; legacy applicability requires review",
    "SFCN-FIREWALL": "FIPS 140-3 — certificate mapping not supplied",
    "CNHE": "FIPS 140-3 — certificate mapping not supplied",
    "SCC": "Active — tracker evidence link requires deployment correlation",
    "ADC": "Historical",
    "VA": "Target update for FIPS 140-3; certificate mapping not supplied",
    "SWG-ROAMING-CLIENT": "Active",
}

# User-reviewed spelling/duplicate rows are presented as one planning row while
# their original source rows remain attached for auditability.
_MERGED_TEAM_KEYS: dict[str, tuple[str, ...]] = {
    "SCC": ("SCC", "SCC-BACKEND"),
    "DISCOVERY": ("DISCOVERY", "RESOURCE-DISCOVERY"),
}
_MERGED_SOURCE_KEYS = {
    source_key
    for canonical_key, source_keys in _MERGED_TEAM_KEYS.items()
    for source_key in source_keys
    if source_key != canonical_key
}


def _tracker_row(row_key: str) -> dict[str, Any]:
    source_keys = _MERGED_TEAM_KEYS.get(row_key, (row_key,))
    source_rows = [_TEAM_ROWS[key] for key in source_keys]

    def combined(field: str) -> str:
        values = list(dict.fromkeys(row[field] for row in source_rows if row[field]))
        return " / ".join(values)

    return {
        "team": source_rows[0]["team"],
        "owner": combined("owner"),
        "lead": combined("lead"),
        "il2": combined("il2"),
        "il5": combined("il5"),
        "cmvp_mapping": " / ".join(
            dict.fromkeys(
                value
                for key in source_keys
                if (value := _CMVP_MAPPING_BY_TEAM.get(key, ""))
            )
        ),
        "source_teams": [row["team"] for row in source_rows],
        "source_rows": [dict(row) for row in source_rows],
    }

# A catalog group can map to multiple source rows only where the user asked for
# a merge.  The order is retained for provenance/display.
GROUP_TEAM_KEYS: dict[str, tuple[str, ...]] = {
    "apix": ("APIX",),
    "apix-no-cbom": ("APIX",),
    "sfcn-ravpn": ("SFCN-RAVPN",),
    "zta-bap": ("ZTA-BAP",),
    "zta-calp": ("ZTA-CLAP",),
    "brain": ("BRAIN",),
    "data-platform": ("DATA-PLATFORM",),
    "metering": ("METERING",),
    "reporting": ("REPORTING",),
    "unified-policy": ("UNIFIED-POLICY",),
    "swg-proxy": ("SWG-PROXY",),
    "opc": ("OPC",),
    "dns-platform": ("DNS-PLATFORM",),
    "disthost": ("DISTHOST",),
    "download-service": ("DOWNLOAD-SERVICE",),
    "landers": ("LANDERS",),
    "contraast": ("CONTRAAST",),
    "knex": ("KNEX",),
    "pac-cbom": ("PAC-CSC-OVD-TIG",),
    "taac-cbom": ("PAC-CSC-OVD-TIG",),
    "app-control": ("PAC-CSC-OVD-TIG",),
    "scc-backend": ("SCC",),
    "discovery": ("DISCOVERY",),
    "avengers": ("FRUP-MICROAPPS",),
    # Scanner-generated CBOMs contribute candidate inventory evidence only;
    # they do not establish module validation or an in-scope deployment.
    "fis-sma-threatgrid": ("FIS-SMA-THREATGRID",),
    "cnhe": ("CNHE",),
    "dw-volt": ("DW-VOLT",),
    "ovd-app-discovery": ("OVD-APP-DISCOVERY",),
    "saasapi": ("SAASAPI",),
    "identity-core": ("IDENTITY-CORE",),
    "identity-apps": ("IDENTITY-APPS",),
    "dlp": ("DLP",),
    "sfcn-firewall": ("SFCN-FIREWALL",),
    "frouter": ("FROUTER",),
    "adc": ("ADC",),
    "va": ("VA",),
    "android-no-cbom": ("ANDROID",),
    "swg-roaming-client-no-cbom": ("SWG-ROAMING-CLIENT",),
    "rsm-secure-client-no-cbom": ("RSM-SECURE-CLIENT",),
    "ios-no-cbom": ("IOS",),
    "on-prem-clients": ("ON-PREM-CLIENTS",),
}


def _milestone(raw: str, label: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {"label": label, "raw_value": "", "status": "not_supplied", "date": None}
    if raw.casefold().startswith("na"):
        return {"label": label, "raw_value": raw, "status": "not_applicable", "date": None}
    # A tracker cell may contain a firm date plus explanatory or relative text.
    # Preserve the entire cell, but use only the explicit date for scheduling.
    numeric_date = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\b", raw)
    if numeric_date:
        value = numeric_date.group(1)
        fmt = "%Y-%m-%d" if "-" in value else "%m/%d/%Y"
        try:
            parsed = datetime.strptime(value, fmt).date()
            return {"label": label, "raw_value": raw, "status": "date", "date": parsed.isoformat()}
        except ValueError:
            pass
    named_date = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]+)[,\s-]+(\d{4})\b",
        raw,
        flags=re.IGNORECASE,
    )
    if named_date:
        month = named_date.group(2)
        if month.casefold() == "sept":
            month = "Sep"
        try:
            parsed = datetime.strptime(
                f"{named_date.group(1)}-{month}-{named_date.group(3)}", "%d-%b-%Y"
            ).date()
            return {"label": label, "raw_value": raw, "status": "date", "date": parsed.isoformat()}
        except ValueError:
            pass
    day_month = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s*-?\s*([A-Za-z]+)", raw)
    if day_month:
        try:
            month = day_month.group(2)
            if month.casefold() == "sept":
                month = "Sep"
            parsed = datetime.strptime(
                f"{day_month.group(1)}-{month}-2026", "%d-%b-%Y"
            ).date()
            return {"label": label, "raw_value": raw, "status": "date", "date": parsed.isoformat()}
        except ValueError:
            pass
    if re.fullmatch(r"[A-Za-z]+\s+\d{4}", raw):
        return {"label": label, "raw_value": raw, "status": "partial_date", "date": None}
    # Relative commitments are retained in the evidence contract, but ignored
    # by mitigation-date calculations and the default UI.
    return {"label": label, "raw_value": raw, "status": "unparseable_or_relative", "date": None}


def _cmvp_disposition(raw: str) -> dict[str, Any]:
    """Classify tracker language without upgrading it to validation evidence."""
    normalized = raw.casefold()
    if any(marker in normalized for marker in ("in-test", "in test", "testing", "in-progress", "in progress")):
        value = "cmvp_in_process"
    elif (
        "active" in normalized
        and "fips 140-2" not in normalized
        and "#4282" not in normalized
    ) or any(certificate in normalized for certificate in ("#4747", "#4985", "#5160")):
        value = "active_certificate"
    elif any(marker in normalized for marker in ("historical", "fips 140-2", "#4282")):
        value = "historical_or_legacy"
    else:
        value = "not_determined"
    return {
        "status": value,
        "raw_value": raw,
        "evidence_grade": "user_asserted",
        "review_required": True,
    }


def _delivery_wave(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Map explicit group IL2 commitments into the three requested delivery waves."""
    milestones = [_milestone(row["il2"], "IL2") for row in rows]
    dates = sorted({entry["date"] for entry in milestones if entry["status"] == "date"})
    raw_values = [entry["raw_value"] for entry in milestones if entry["raw_value"]]
    farthest = dates[-1] if dates else None
    if farthest and farthest <= "2026-10-31":
        wave, label, target = "october_2026", "October 2026", "2026-10-31"
    elif farthest and farthest <= "2026-12-31":
        wave, label, target = "december_2026", "December 2026", "2026-12-31"
    elif (farthest and farthest <= "2027-03-31") or any(
        "march 2027" in value.casefold() for value in raw_values
    ):
        wave, label, target = "march_2027", "March 2027", "2027-03-31"
    else:
        wave, label, target = "uncommitted", "Uncommitted", None
    return {
        "wave": wave,
        "label": label,
        "target_date": target,
        "farthest_explicit_il2_date": farthest,
        "raw_il2_values": raw_values,
        "basis": "Team Tracker group-level IL2 planning metadata",
    }


def _profile(group_slug: str) -> dict[str, Any]:
    canonical_group = _slug(group_slug)
    row_keys = GROUP_TEAM_KEYS.get(canonical_group, ())
    rows = [_tracker_row(key) for key in row_keys]
    owners = list(dict.fromkeys(row["owner"] for row in rows if row["owner"]))
    leads = list(dict.fromkeys(row["lead"] for row in rows if row["lead"]))
    return {
        "service_group": canonical_group,
        "mapping_status": "mapped" if rows else "not_mapped",
        "empty_service_category": False,
        "owners": owners,
        "leads": leads,
        "delivery_wave": _delivery_wave(rows),
        "tracker_rows": [
            {
                "team": row["team"],
                "owner": row["owner"] or None,
                "lead": row["lead"] or None,
                "il2": _milestone(row["il2"], "IL2"),
                "il5": _milestone(row["il5"], "IL5"),
                "cmvp_mapping": row["cmvp_mapping"] or None,
                "cmvp_disposition": _cmvp_disposition(row["cmvp_mapping"]),
                "source_teams": row["source_teams"],
                "source_rows": row["source_rows"],
            }
            for row in rows
        ],
    }


def team_milestones() -> dict[str, Any]:
    """Return a stable, provenance-bearing group milestone contract."""
    groups = [_profile(group) for group in sorted(GROUP_TEAM_KEYS)]
    mapped_groups_by_row: dict[str, list[str]] = {}
    for group, row_keys in GROUP_TEAM_KEYS.items():
        for row_key in row_keys:
            mapped_groups_by_row.setdefault(row_key, []).append(group)
    display_rows = [
        (key, _tracker_row(key))
        for key in _TEAM_ROWS
        if key not in _MERGED_SOURCE_KEYS
    ]
    all_tracker_rows = [
        {
            "team": row["team"],
            "owner": row["owner"] or None,
            "lead": row["lead"] or None,
            "il2": _milestone(row["il2"], "IL2"),
            "il5": _milestone(row["il5"], "IL5"),
            "cmvp_mapping": row["cmvp_mapping"] or None,
            "cmvp_disposition": _cmvp_disposition(row["cmvp_mapping"]),
            "delivery_wave": _delivery_wave([row]),
            "mapped_service_groups": sorted(mapped_groups_by_row.get(key, [])),
            "mapping_status": "mapped" if key in mapped_groups_by_row else "retained_unmapped",
            "source_teams": row["source_teams"],
            "source_rows": row["source_rows"],
        }
        for key, row in sorted(display_rows, key=lambda item: item[1]["team"].casefold())
    ]
    material = repr((groups, all_tracker_rows)).encode("utf-8")
    return {
        "source": {**TRACKER_SOURCE, "payload_sha256": hashlib.sha256(material).hexdigest()},
        "disclaimer": "Team tracker data is planning metadata only; it is not validation evidence or an assessor conclusion.",
        "groups": groups,
        "all_tracker_rows": all_tracker_rows,
    }


def enrich_poam_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach group planning context to draft POA&M candidates.

    Only explicit full IL2 dates may populate scheduled_completion_date. When a
    candidate spans groups, its candidate mitigation date is the farthest such
    date.  IL5 stays display-only group planning metadata.
    """
    for item in items:
        group_references = item.get("affected_service_groups") or item.get("affected_services", [])
        groups = sorted({_slug(str(service).rsplit("/", 1)[-1]) for service in group_references})
        profiles = [_profile(group) for group in groups]
        profiles_by_group = {profile["service_group"]: profile for profile in profiles}
        il2_rows = [row["il2"] for profile in profiles for row in profile["tracker_rows"]]
        explicit_dates = sorted({row["date"] for row in il2_rows if row["status"] == "date" and row["date"]})
        owners = list(dict.fromkeys(owner for profile in profiles for owner in profile["owners"]))
        item["team_tracker_milestones"] = {
            "source": team_milestones()["source"],
            "group_milestones": profiles,
            "il2_mitigation_date_rule": "farthest explicit parseable IL2 date across affected service groups",
            "il2_explicit_dates": explicit_dates,
        }
        item["milestone_mitigation_date"] = explicit_dates[-1] if explicit_dates else None
        item["scheduled_completion_date"] = item["milestone_mitigation_date"]
        item["responsible_owner"] = "; ".join(owners) if owners else "Not supplied — team confirmation required"
        for link in item.get("service_scope_links", []):
            profile = profiles_by_group.get(_slug(str(link.get("service_group") or "")))
            if not profile:
                continue
            link["planning"] = {
                "owners": profile["owners"],
                "leads": profile["leads"],
                "delivery_wave": profile["delivery_wave"],
                "tracker_rows": profile["tracker_rows"],
                "eta_inheritance": "Inherited from the mapped service-group Team Tracker row",
            }
        item["milestone_deliverables"] = [
            {
                "service_group": profile["service_group"],
                "owners": profile["owners"],
                "leads": profile["leads"],
                "delivery_wave": profile["delivery_wave"],
                "tracker_rows": profile["tracker_rows"],
            }
            for profile in profiles
        ]
        owner_aware_material = "|".join(
            [
                str(item.get("policy_version") or ""),
                ",".join(item.get("gap_codes") or []),
                str(item.get("subject_identity") or ""),
                str(item.get("remediation_plan") or ""),
                item["responsible_owner"],
                str(item.get("ato_boundary") or ""),
            ]
        )
        item["owner_aware_dedupe_key"] = hashlib.sha256(
            owner_aware_material.encode("utf-8")
        ).hexdigest()
        if explicit_dates:
            item["planned_milestone"] = "IL2 group planning milestone: " + explicit_dates[-1]
        else:
            item["planned_milestone"] = "IL2 milestone not supplied as an explicit date — team confirmation required."
    return items


def portfolio_delivery_waves(group_slugs: list[str] | None = None) -> list[dict[str, Any]]:
    """Return group-level IL2 commitments in the requested Oct/Dec/Mar waves."""
    selected_values = list(GROUP_TEAM_KEYS) if group_slugs is None else group_slugs
    selected = sorted({_slug(value) for value in selected_values})
    profiles = [_profile(group) for group in selected]
    wave_order = ("october_2026", "december_2026", "march_2027", "uncommitted")
    result: list[dict[str, Any]] = []
    for wave in wave_order:
        scoped = [profile for profile in profiles if profile["delivery_wave"]["wave"] == wave]
        if not scoped and wave == "uncommitted":
            continue
        metadata = scoped[0]["delivery_wave"] if scoped else {
            "label": {
                "october_2026": "October 2026",
                "december_2026": "December 2026",
                "march_2027": "March 2027",
            }[wave],
            "target_date": {
                "october_2026": "2026-10-31",
                "december_2026": "2026-12-31",
                "march_2027": "2027-03-31",
            }[wave],
        }
        result.append(
            {
                "wave": wave,
                "label": metadata["label"],
                "target_date": metadata.get("target_date"),
                "service_group_count": len(scoped),
                "service_groups": [
                    {
                        "service_group": profile["service_group"],
                        "owners": profile["owners"],
                        "leads": profile["leads"],
                        "farthest_explicit_il2_date": profile["delivery_wave"][
                            "farthest_explicit_il2_date"
                        ],
                        "raw_il2_values": profile["delivery_wave"]["raw_il2_values"],
                        "cmvp_dispositions": sorted(
                            {
                                row["cmvp_disposition"]["status"]
                                for row in profile["tracker_rows"]
                            }
                        ),
                    }
                    for profile in scoped
                ],
                "planning_metadata_only": True,
            }
        )
    return result


def build_portfolio_poam_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build exactly two requested portfolio candidates without hiding asset evidence."""
    specifications = (
        {
            "portfolio_poam_id": "FIPS3-PORTFOLIO-ACTIVE-CERT",
            "dimension": "active_certificate_migration",
            "match_status": "active_certificate",
            "title": "Migrate deployments to deployment-matched FIPS 140-3 modules with active certificates",
            "condition": (
                "Team Tracker planning data identifies an active certificate or named active FIPS 140-3 "
                "module, while deployment-to-certificate correlation and approved-mode evidence still require review."
            ),
        },
        {
            "portfolio_poam_id": "FIPS3-PORTFOLIO-CMVP-PIPELINE",
            "dimension": "cmvp_in_test_or_in_progress",
            "match_status": "cmvp_in_process",
            "title": "Track migrations dependent on modules in CMVP In-Test or In-Progress",
            "condition": (
                "Team Tracker planning data identifies a target module as testing, In-Test, or In-Progress; "
                "no active validation conclusion is inferred."
            ),
        },
    )
    result: list[dict[str, Any]] = []
    all_linked_candidate_ids: set[str] = set()
    for specification in specifications:
        candidate_ids: set[str] = set()
        matched_links: list[dict[str, Any]] = []
        for item in items:
            for link in item.get("service_scope_links", []):
                planning = link.get("planning") or {}
                statuses = {
                    row.get("cmvp_disposition", {}).get("status")
                    for row in planning.get("tracker_rows", [])
                }
                if specification["match_status"] not in statuses:
                    continue
                matched_links.append(link)
                if item.get("poam_candidate_id"):
                    candidate_ids.add(str(item["poam_candidate_id"]))
        all_linked_candidate_ids.update(candidate_ids)
        service_groups = sorted(
            {str(link["service_group_ref"]) for link in matched_links}
        )
        service_records = sorted(
            {
                (
                    int(link["document_id"]),
                    str(link["service_record_name"]),
                    str(link.get("source_path") or ""),
                )
                for link in matched_links
            }
        )
        libraries = {
            (
                str(library.get("component_identity") or ""),
                str(library.get("name") or ""),
                str(library.get("version") or ""),
            )
            for link in matched_links
            for library in link.get("libraries", [])
        }
        group_slugs = [reference.rsplit("/", 1)[-1] for reference in service_groups]
        waves = portfolio_delivery_waves(group_slugs)
        dated = sorted(
            {
                str(group.get("farthest_explicit_il2_date"))
                for wave in waves
                for group in wave["service_groups"]
                if group.get("farthest_explicit_il2_date")
            }
        )
        owners = sorted(
            {
                owner
                for link in matched_links
                for owner in (link.get("planning") or {}).get("owners", [])
            }
        )
        result.append(
            {
                **specification,
                "status": "Draft portfolio candidate — authorized review required",
                "control_id": "SC-13",
                "responsible_owners": owners,
                "scheduled_completion_date": dated[-1] if dated else None,
                "mitigation_date_rule": "Farthest explicit IL2 date across linked service groups",
                "linked_candidate_ids": sorted(candidate_ids),
                "linked_candidate_count": len(candidate_ids),
                "affected_service_groups": service_groups,
                "affected_service_group_count": len(service_groups),
                "affected_service_records": [
                    {"document_id": document_id, "name": name, "source_path": path}
                    for document_id, name, path in service_records
                ],
                "affected_service_record_count": len(service_records),
                "affected_libraries": [
                    {"component_identity": identity, "name": name, "version": version or None}
                    for identity, name, version in sorted(libraries)
                ],
                "affected_library_count": len(libraries),
                "service_scope_links": matched_links,
                "milestone_deliverables": waves,
                "evidence_basis": "Team Tracker CMVP mapping plus linked catalog candidate evidence",
                "evidence_grade": "user_asserted planning metadata joined to inventory evidence",
                "merge_decision": "review_required",
                "merge_blockers": [
                    "Confirm the exact module, certificate, tested version, operational environment, and approved mode.",
                    "Confirm every linked service record is deployed inside the authoritative ATO boundary.",
                    "Confirm one accountable owner and remediation plan can govern the linked scope.",
                    "Confirm each group-level IL2 commitment and retain exceptions as separate milestones.",
                ],
                "candidate_only": True,
            }
        )
    unclassified = sorted(
        str(item["poam_candidate_id"])
        for item in items
        if item.get("poam_candidate_id") not in all_linked_candidate_ids
    )
    for row in result:
        row["unclassified_candidate_count"] = len(unclassified)
        row["unclassified_candidate_ids"] = unclassified
    return result
