"""Paper-record lookup for IDOMS runtime inputs.

The workbook is the human-audited source of record. A small set of
source-annotated runtime values absent from the workbook is listed below.
The resolver never applies a code default or infers an energy from a benchmark
with a different definition.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook


WORKBOOK_PATH = Path(__file__).resolve().parent / "IDOMS_Master_Energetics_Database.xlsx"
SHEET_NAME = "Energy Records"

# Paper-reported values that are needed by the runtime but are not yet present
# as rows in the workbook. Keep their source and scope explicit here.
PAPER_RUNTIME_VALUES = {
    "fe_cr_lattice": {
        "Fe_A": 2.83,
        "Cr_A": 2.84,
        "source_id": "S3",
        "doi": "10.1103/PhysRevB.99.014110",
        "paper_location": "PDF p. 4; pure-element equilibrium lattice constants",
        "method_location": "PDF p. 3; lattice constant linearly interpolated by total Fe-Cr composition",
        "verification": "Endpoint values checked in the Results passage; interpolation method checked independently in Computational Methods.",
    },
    "w_lattice": {
        "pristine_value_A": 3.172,
        "pristine_source_id": "S4",
        "pristine_doi": "10.1063/1.3386515",
        "pristine_paper_location": "PDF p. 5, Table I; calculated W lattice constant, this work",
        "pristine_verification": "Value transcribed from the Table I row and cross-checked against the paper's statement comparing its calculated value with experimental 3.165 Å.",
        "vacancy_value_A": 3.165,
        "vacancy_source_id": "S7",
        "vacancy_doi": "10.1016/j.actamat.2015.04.052",
        "vacancy_paper_location": "PDF p. 2; experimental W lattice parameter used in the calculations",
        "vacancy_verification": "Value checked in the Methods passage and against the fixed-cell description for vacancy calculations.",
    },
    "w_vacancy_h1_attempt_frequency": {
        "value_Hz": 0.85e13,
        "source_id": "S7",
        "doi": "10.1016/j.actamat.2015.04.052",
        "paper_location": "PDF p. 7 (printed p. 313); attempt frequencies for vacancy occupancy j=1..6",
        "verification": "The j=1 value is transcribed from the explicit frequency list and checked against the paper's definition of the occupancy-specific attempt frequency in Eq. (24).",
    },
}


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


def _paper_record(key: str, value: Optional[float], unit: str, *, source_id: str,
                  doi: str, location: str, status: str = "PAPER_REPORTED",
                  verification: str, mapping: Optional[str] = None) -> Dict[str, Any]:
    return {
        "key": key, "value": value, "unit": unit, "status": status,
        "source_id": source_id, "doi": doi, "paper_location": location,
        "verification": verification, "mapping_or_limit": mapping,
    }


def _paper_lattice_parameter(setup: Dict[str, Any]) -> tuple[Optional[float], Dict[str, Any]]:
    host = str(setup.get("host", "")).strip()
    structure = str(setup.get("crystal_structure", "")).strip().upper()
    composition = {str(k).strip(): float(v) for k, v in
                   (setup.get("composition_at_percent") or {}).items()}
    if structure != "BCC":
        return None, {"reason": "The supplied lattice-parameter records apply to BCC crystals only."}
    if host == "Fe":
        unsupported = {el: pct for el, pct in composition.items() if pct > 0 and el != "Cr"}
        if unsupported:
            return None, {
                "reason": "The supplied papers do not report a composition-dependent BCC Fe lattice parameter for this alloying element set.",
                "unsupported_elements": sorted(unsupported),
            }
        data = PAPER_RUNTIME_VALUES["fe_cr_lattice"]
        cr_fraction = composition.get("Cr", 0.0) / 100.0
        if not 0.0 <= cr_fraction <= 1.0:
            return None, {"reason": "Cr composition must be between 0 and 100 at.%."}
        value = data["Fe_A"] + cr_fraction * (data["Cr_A"] - data["Fe_A"])
        return value, {
            "status": "DERIVED_PAPER_INTERPOLATION" if cr_fraction else "PAPER_REPORTED",
            "unit": "Å", "source_id": data["source_id"], "doi": data["doi"],
            "paper_location": f"{data['paper_location']}; {data['method_location']}",
            "verification": data["verification"],
            "reported_endpoints_A": {"Fe": data["Fe_A"], "Cr": data["Cr_A"]},
            "cr_at_percent": composition.get("Cr", 0.0),
            "mapping_or_limit": "Paper method applies to binary Fe-Cr composition; no C-dependent correction is applied. Endpoints are reported to 0.01 Å, so finer interpolation decimals are arithmetic outputs rather than independently reported precision.",
        }
    if host == "W" and not any(v > 0 for v in composition.values()):
        data = PAPER_RUNTIME_VALUES["w_lattice"]
        vacancy_enabled = int(setup.get("vacancy_count", 0) or 0) > 0
        prefix = "vacancy" if vacancy_enabled else "pristine"
        return data[f"{prefix}_value_A"], {
            "status": "PAPER_REPORTED", "unit": "Å",
            "source_id": data[f"{prefix}_source_id"],
            "doi": data[f"{prefix}_doi"],
            "paper_location": data[f"{prefix}_paper_location"],
            "verification": data[f"{prefix}_verification"],
            "mapping_or_limit": ("Experimental W lattice parameter used by S7 for vacancy calculations." if vacancy_enabled
                                 else "Calculated pristine W lattice parameter from S4; the experimental comparator is 3.165 Å."),
        }
    return None, {"reason": "No paper-supported lattice parameter is available for this host/composition."}


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

    lattice_a, lattice_record = _paper_lattice_parameter(setup)
    if lattice_a is None:
        values.append({"key": "lattice_parameter_A", "value": None,
                       "unit": "Å", "status": "MISSING",
                       "reported_value_or_wording": lattice_record.get("reason")})
        missing.append({"key": "lattice_parameter_A", "reason": lattice_record.get("reason", "No compatible paper value.")})
    else:
        values.append({"key": "lattice_parameter_A", "value": lattice_a,
                       "unit": "Å", **lattice_record})

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

    vacancy_count = int(setup.get("vacancy_count", 0) or 0)
    vacancy_parameters: Dict[str, float] = {}
    if vacancy_count > 0:
        if host == "Fe":
            missing.append({
                "key": "vacancy_trapping_barrier_W_model",
                "reason": "The supplied Fe vacancy paper reports H-vacancy binding but not the transition barrier and rate data needed by this solver.",
            })
            values.append({"key": "vacancy_trapping_barrier_W_model", "value": None,
                           "unit": "eV", "status": "MISSING",
                           "reported_value_or_wording": "Fe vacancy kinetics are not solver-ready in the supplied papers."})
        elif host == "W" and structure == "BCC" and species == "H" and supported_network:
            def find_vacancy_record(parameter: str) -> Optional[Dict[str, Any]]:
                for row in records:
                    if (row.get("Source ID") == "S7" and row.get("Host") == "W"
                            and row.get("Phase") == "bcc W" and row.get("Interstitial") == "H"
                            and row.get("Parameter") == parameter
                            and "1 H" in str(row.get("Configuration", ""))
                            and row.get("Status") == "PAPER_REPORTED"
                            and row.get("Unit") == "eV"
                            and isinstance(row.get("Numeric value"), (int, float))):
                        return row
                return None

            binding = find_vacancy_record("Incremental H binding e_b,j (DFT)")
            detrap = find_vacancy_record("De-trapping barrier (DFT)")
            if binding and detrap:
                binding_value = float(binding["Numeric value"])
                detrap_value = float(detrap["Numeric value"])
                capture_value = detrap_value + binding_value
                if not math.isfinite(capture_value) or capture_value <= 0:
                    missing.append({"key": "W_vacancy_H1_capture_barrier_eV",
                                    "reason": "The S7 binding and detrapping records do not yield a positive capture barrier under the paper's Figure 4 energy relation."})
                vacancy_parameters["W_vacancy_H1_binding_eV"] = binding_value
                vacancy_parameters["W_vacancy_H1_detrapping_barrier_eV"] = detrap_value
                vacancy_parameters["W_vacancy_H1_capture_barrier_eV"] = capture_value
                values.extend([
                    _as_public_record("W_vacancy_H1_binding_eV", binding, binding_value),
                    _as_public_record("W_vacancy_H1_detrapping_barrier_eV", detrap, detrap_value),
                    _paper_record(
                        "W_vacancy_H1_capture_barrier_eV", capture_value, "eV",
                        source_id="S7", doi="10.1016/j.actamat.2015.04.052",
                        location="PDF p. 7 (printed p. 313); Fig. 4 energy path and Table 3/Table 4",
                        status="DERIVED_FROM_PAPER_RELATION",
                        verification="Derived as the reported DFT detrapping barrier plus the reported negative incremental binding energy (-1.19 eV + 1.39 eV = 0.20 eV); checked against Fig. 4's e_dtp/e_b/e_diff definition and the tabulated values.",
                        mapping="S7 defines e_dtp as binding energy magnitude plus bulk diffusion barrier. The workbook records e_b with its negative energy-change sign, so capture barrier = e_dtp + e_b.",
                    ),
                ])
                attempt = PAPER_RUNTIME_VALUES["w_vacancy_h1_attempt_frequency"]
                vacancy_parameters["W_vacancy_H1_attempt_frequency_Hz"] = attempt["value_Hz"]
                values.append(_paper_record(
                    "W_vacancy_H1_attempt_frequency_Hz", attempt["value_Hz"], "Hz",
                    source_id=attempt["source_id"], doi=attempt["doi"],
                    location=attempt["paper_location"], verification=attempt["verification"],
                ))
            else:
                missing.append({"key": "W_vacancy_H1_paper_parameters",
                                "reason": "The database does not contain both the matching S7 single-H binding and detrapping-barrier records."})
        else:
            missing.append({"key": "vacancy_model",
                            "reason": "The supplied kinetic vacancy data applies to BCC W-H on the tetrahedral network only."})

    return {
        "database": WORKBOOK_PATH.name,
        "sheet": SHEET_NAME,
        "runnable": not missing,
        "resolved_energies_eV": resolved,
        "resolved_vacancy_parameters": vacancy_parameters,
        "lattice_parameter_A": lattice_a,
        "lattice_parameter_resolution": lattice_record,
        "values": values,
        "missing": missing,
        "non_paper_model_rules": [
            "The engine uses its existing boundary-exit rule: surface and bulk exit barriers fall back to the resolved host migration barrier. This is a solver rule, not a paper-reported boundary transition value.",
            "Attempt frequency, Boltzmann constant, geometry cutoffs, and numerical floors remain solver constants outside the paper-energy database.",
        ],
    }
