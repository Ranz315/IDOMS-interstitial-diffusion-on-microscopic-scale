"""Paper-record lookup for IDOMS energy inputs.

The workbook is the human-audited source of record. This module reads only the
flat Energy Records sheet; it never applies a code default or infers an energy
from a benchmark with a different definition.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook


WORKBOOK_PATH = Path(__file__).resolve().parent / "IDOMS_Master_Energetics_Database.xlsx"
SHEET_NAME = "Energy Records"


class EnergeticsDatabaseError(RuntimeError):
    """Raised when the required paper database cannot be read safely."""


@lru_cache(maxsize=1)
def load_energy_records() -> List[Dict[str, Any]]:
    if not WORKBOOK_PATH.is_file():
        raise EnergeticsDatabaseError(
            "The paper energetics workbook is missing: " + str(WORKBOOK_PATH)
        )

    try:
        book = load_workbook(WORKBOOK_PATH, read_only=True, data_only=True)
        if SHEET_NAME not in book.sheetnames:
            raise EnergeticsDatabaseError(
                "The workbook has no 'Energy Records' sheet."
            )
        sheet = book[SHEET_NAME]
        rows = sheet.iter_rows(min_row=4, values_only=True)
        headers = next(rows, None)
        if not headers:
            raise EnergeticsDatabaseError("The Energy Records sheet is empty.")
        names = [str(value).strip() if value is not None else "" for value in headers]
        required = {
            "Host", "Phase", "Interstitial", "Parameter", "Numeric value",
            "Unit", "Source ID", "DOI", "Paper location", "Verification note",
            "IDOMS mapping / limitation", "Status",
        }
        missing_columns = sorted(required.difference(names))
        if missing_columns:
            raise EnergeticsDatabaseError(
                "The Energy Records sheet is missing required columns: "
                + ", ".join(missing_columns)
            )

        records: List[Dict[str, Any]] = []
        for raw in rows:
            if not raw or all(value is None for value in raw):
                continue
            record = {name: raw[index] if index < len(raw) else None
                      for index, name in enumerate(names) if name}
            if not record.get("Parameter"):
                continue
            records.append(record)
        book.close()
        return records
    except EnergeticsDatabaseError:
        raise
    except Exception as exc:
        raise EnergeticsDatabaseError(
            "Could not read the paper energetics workbook: " + str(exc)
        ) from exc


def _as_public_record(key: str, record: Dict[str, Any], value: Optional[float]) -> Dict[str, Any]:
    return {
        "key": key,
        "value": value,
        "unit": record.get("Unit"),
        "status": record.get("Status"),
        "source_id": record.get("Source ID"),
        "doi": record.get("DOI"),
        "paper_location": record.get("Paper location"),
        "reported_definition": record.get("Definition / sign convention"),
        "reference_state": record.get("Reference state"),
        "transition_or_site": record.get("Site / transition"),
        "verification": record.get("Verification note"),
        "mapping_or_limit": record.get("IDOMS mapping / limitation"),
        "reported_value_or_wording": record.get("Reported value / wording"),
    }


def resolve_energy_inputs(setup: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve only compatible paper records; absent values remain missing."""
    records = load_energy_records()
    host = str(setup.get("host", "")).strip()
    structure = str(setup.get("crystal_structure", "")).strip().upper()
    species = str(setup.get("interstitial_species", "")).strip()
    requested_network = str(setup.get("site_network", "auto")).strip()
    effective_network = ("tetrahedral" if species in {"H", "D", "T"} else "octahedral") \
        if requested_network == "auto" else requested_network
    phase = "bcc α-Fe" if host == "Fe" and structure == "BCC" else (
        "bcc W" if host == "W" and structure == "BCC" else None
    )
    supported_network = species == "H" and effective_network == "tetrahedral"

    resolved: Dict[str, float] = {}
    values: List[Dict[str, Any]] = []
    missing: List[Dict[str, str]] = []

    def find_record(parameter: str, statuses: set[str]) -> Optional[Dict[str, Any]]:
        candidates = [row for row in records
                      if row.get("Host") == host
                      and row.get("Phase") == phase
                      and row.get("Interstitial") == species
                      and row.get("Parameter") == parameter
                      and str(row.get("Unit", "")).strip() == "eV"]
        for row in candidates:
            if row.get("Status") not in statuses:
                continue
            value = row.get("Numeric value")
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return row
        # Retain source-specific qualitative evidence when it explains a missing
        # numeric field, rather than replacing it with a generic no-record note.
        return next((row for row in candidates
                     if row.get("Status") != "MISSING" and row.get("Source ID")),
                    next((row for row in candidates if row.get("Source ID")), None))

    def require(key: str, parameter: str, statuses: set[str], reason: str) -> None:
        record = find_record(parameter, statuses)
        numeric = record.get("Numeric value") if record else None
        if isinstance(numeric, (int, float)) and math.isfinite(float(numeric)):
            resolved[key] = float(numeric)
            values.append(_as_public_record(key, record, float(numeric)))
        else:
            detail = reason
            if record:
                wording = record.get("Reported value / wording")
                if wording and str(wording).strip().upper() != "MISSING":
                    detail = str(wording)
                else:
                    detail = str(record.get("Definition / sign convention")
                                 or record.get("IDOMS mapping / limitation") or reason)
                values.append(_as_public_record(key, record, None))
            else:
                values.append({"key": key, "value": None, "unit": "eV",
                               "status": "MISSING", "reported_value_or_wording": reason})
            missing.append({"key": key, "reason": detail})

    if phase is None or not supported_network:
        missing.append({
            "key": "host_migration_barrier",
            "reason": "The supplied papers provide compatible baseline barriers only for BCC Fe–H and BCC W–H on the tetrahedral network.",
        })
        values.append({"key": "host_migration_barrier", "value": None, "unit": "eV",
                       "status": "MISSING", "reported_value_or_wording": "No matching paper record."})
    else:
        if host == "W":
            baseline_parameter = "host_migration_barrier candidate"
            baseline_note = "No paper-reported BCC W–H adjacent tetrahedral migration barrier was found."
        else:
            baseline_parameter = "host_migration_barrier"
            baseline_note = "No paper-reported BCC Fe–H baseline migration barrier was found."
        require("host_migration_barrier", baseline_parameter, {"PAPER_REPORTED"}, baseline_note)

    if phase is not None and supported_network:
        for element in setup.get("alloying_elements", []):
            element = str(element).strip()
            site_key = f"{element}_site_energy_shift"
            saddle_key = f"{element}_saddle_energy_shift"
            if host == "Fe" and element == "C" and structure == "BCC":
                require(site_key, "C_site_energy_shift (IDOMS ΔU)",
                        {"DERIVED_MAPPING_NOT_PAPER_VALUE"},
                        "No paper-supported H–C site mapping is available.")
            else:
                require(site_key, site_key, {"PAPER_REPORTED"},
                        f"No compatible numeric paper value for {site_key}.")
            require(saddle_key, saddle_key, {"PAPER_REPORTED"},
                    f"No compatible numeric paper value for {saddle_key}.")

    return {
        "database": WORKBOOK_PATH.name,
        "sheet": SHEET_NAME,
        "runnable": not missing,
        "resolved_energies_eV": resolved,
        "values": values,
        "missing": missing,
        "non_paper_model_rules": [
            "The engine uses its existing boundary-exit rule: surface and bulk exit barriers fall back to the resolved host migration barrier. This is a solver rule, not a paper-reported boundary transition value.",
            "Attempt frequency, Boltzmann constant, geometry cutoffs, and numerical floors remain solver constants outside the paper-energy database.",
        ],
    }
