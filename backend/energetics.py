"""Paper-record lookup for IDOMS runtime inputs.

The workbook is the human-audited source of record. A small set of
source-annotated runtime values absent from the workbook is listed below.
The resolver never applies a code default or infers an energy from a benchmark
with a different definition.
"""
from __future__ import annotations

from functools import lru_cache
import math
import os
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
        "vacancy_value_A": 3.187,
        "vacancy_source_id": "S7",
        "vacancy_doi": "10.1016/j.actamat.2015.04.052",
        "vacancy_paper_location": "PDF p. 2; optimized BCC cell parameter, with vacancy calculations later performed at fixed cell parameter",
        "vacancy_verification": "Methods reports a = 3.187 Å as the optimized cell parameter; the 3.165 Å value in the same passage is explicitly the experimental comparison. Section 3.3 says the vacancy-cell parameter was fixed.",
    },
    "w_vacancy_h1_attempt_frequency": {
        "value_Hz": 0.85e13,
        "source_id": "S7",
        "doi": "10.1016/j.actamat.2015.04.052",
        "paper_location": "PDF p. 7 (printed p. 313); attempt frequencies for vacancy occupancy j=1..6",
        "verification": "The j=1 value is transcribed from the explicit frequency list and checked against the paper's definition of the occupancy-specific attempt frequency in Eq. (24).",
    },
    "w_vacancy_attempt_frequencies": {
        "values_Hz": [0.85e13, 0.83e13, 1.45e13, 0.99e13, 1.07e13, 0.98e13],
        "source_id": "S7",
        "doi": "10.1016/j.actamat.2015.04.052",
        "paper_location": "PDF p. 7 (printed p. 313); Eq. (24), mean frequencies for j=1..6 over 300–1000 K",
        "verification": "All six values transcribed from the explicit ordered list in the paper and matched to j=1..6; values are means over 300–1000 K, not temperature-specific frequencies.",
    },
    "w_vacancy_initial_population": {
        "relative_to_vh6": [5.74e-37, 2.05e-25, 1.01e-16, 1.83e-8, 2.69e-2, 1.0],
        "source_id": "S7",
        "doi": "10.1016/j.actamat.2015.04.052",
        "paper_location": "PDF p. 9 (printed p. 315), Table 5; x_H=10^-5 H/W, T=300 K; x_VHj normalized to VH6",
        "verification": "Values transcribed from the normalized x_VHj row and independently checked by dividing the Table 5 x_j values by the VH6 value (1.63e-6). These are model-calculated starting populations, not measured occupancies.",
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


@lru_cache(maxsize=128)
def _tcfe15_bcc_lattice_parameter_cached(
    cr_at_percent: float, c_at_percent: float, temperature_K: float,
) -> tuple[Optional[float], Dict[str, Any]]:
    """Calculate a constrained single-phase BCC lattice parameter through TC-Python.

    TCFE15 is proprietary and is deliberately neither included nor emulated here.
    The result is obtained only from the user's licensed Thermo-Calc installation.
    """
    database = os.environ.get("IDOMS_TCFE_DATABASE", "TCFE15").strip()
    try:
        from tc_python import TCPython, ThermodynamicQuantity
    except (ImportError, OSError) as exc:
        return None, {
            "status": "MISSING_EXTERNAL_LICENSED_DATABASE",
            "database": database,
            "reason": "Fe–Cr–C lattice parameter requires Thermo-Calc TCFE15 and TC-Python in the backend Python environment. Neither is bundled with IDOMS.",
            "detail": str(exc),
        }

    elements = ["Fe", "C"] + (["Cr"] if cr_at_percent > 0 else [])
    try:
        with TCPython() as session:
            available = session.get_databases()
            if database not in available:
                return None, {
                    "status": "MISSING_EXTERNAL_LICENSED_DATABASE",
                    "database": database,
                    "reason": f"Thermo-Calc does not report {database} as available in this installation. Check the database name and license.",
                }
            calc = (session.select_database_and_elements(database, elements)
                    .get_system().with_single_equilibrium_calculation())
            calc.set_phase_to_suspended("ALL_PHASES")
            calc.set_phase_to_entered("BCC_A2")
            calc.set_condition(ThermodynamicQuantity.temperature(), temperature_K)
            if cr_at_percent > 0:
                calc.set_condition(
                    ThermodynamicQuantity.mole_fraction_of_a_component("Cr"),
                    cr_at_percent / 100.0,
                )
            calc.set_condition(
                ThermodynamicQuantity.mole_fraction_of_a_component("C"),
                c_at_percent / 100.0,
            )
            result = calc.calculate()
            molar_volume_m3_mol = float(result.get_value_of(
                ThermodynamicQuantity.molar_volume_of_phase("BCC_A2")
            ))
            # TCFE's molar volume is per mole of BCC lattice sites; a BCC cell
            # contains two lattice sites. Convert m^3/mol to cubic-cell edge Å.
            avogadro = 6.02214076e23
            lattice_a_A = (2.0 * molar_volume_m3_mol / avogadro) ** (1.0 / 3.0) * 1e10
            if not math.isfinite(lattice_a_A) or lattice_a_A <= 0:
                return None, {
                    "status": "TCFE_CALCULATION_FAILED", "database": database,
                    "reason": "TCFE15 returned a nonphysical BCC_A2 molar volume.",
                    "molar_volume_m3_mol": molar_volume_m3_mol,
                }
            return lattice_a_A, {
                "status": "TCFE_CALCULATED",
                "database": database,
                "database_version": database,
                "method": "TC-Python constrained single-phase BCC_A2; lattice parameter derived from TCFE molar volume and two BCC lattice sites per cubic cell.",
                "molar_volume_m3_mol": molar_volume_m3_mol,
                "temperature_K": temperature_K,
                "cr_at_percent": cr_at_percent,
                "c_at_percent": c_at_percent,
                "unit": "Å",
                "mapping_or_limit": "CALPHAD database calculation, not a paper-reported value. Other phases were suspended to obtain the homogeneous BCC_A2 matrix lattice parameter at the nominal input composition; precipitation/microstructure partitioning is not modeled by this lattice calculation.",
            }
    except Exception as exc:
        return None, {
            "status": "TCFE_CALCULATION_FAILED",
            "database": database,
            "reason": "The TCFE15 BCC_A2 lattice calculation failed. Confirm the TC-Python/Thermo-Calc versions, TCFE license, and that BCC_A2 supports the entered Fe–Cr–C composition at this temperature.",
            "detail": str(exc),
        }


def _paper_lattice_parameter(setup: Dict[str, Any]) -> tuple[Optional[float], Dict[str, Any]]:
    host = str(setup.get("host", "")).strip()
    structure = str(setup.get("crystal_structure", "")).strip().upper()
    composition = {str(k).strip(): float(v) for k, v in
                   (setup.get("composition_at_percent") or {}).items()}
    if structure != "BCC":
        return None, {"reason": "The supplied lattice-parameter records apply to BCC crystals only."}
    if host == "Fe":
        if any(not math.isfinite(pct) or pct < 0 for pct in composition.values()):
            return None, {"reason": "Alloying-element atomic percentages must be finite and nonnegative."}
        if sum(composition.values()) >= 100:
            return None, {"reason": "Total alloying content must be less than 100 at.%."}
        c_fraction = composition.get("C", 0.0)
        cr_fraction = composition.get("Cr", 0.0)
        unsupported = {el: pct for el, pct in composition.items()
                       if pct > 0 and el not in {"C", "Cr"}}
        if unsupported:
            return None, {
                "reason": "TCFE15 integration currently supports only Fe–Cr–C BCC compositions.",
                "unsupported_elements": sorted(unsupported),
            }
        if c_fraction > 0:
            return _tcfe15_bcc_lattice_parameter_cached(
                cr_fraction, c_fraction, float(setup.get("temperature_K", 298.15))
            )
        data = PAPER_RUNTIME_VALUES["fe_cr_lattice"]
        cr_fraction = cr_fraction / 100.0
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
            "mapping_or_limit": ("S7 optimized DFT cell parameter used for its fixed-cell vacancy calculations. This is a source-model cell setting, not a claim that one vacancy changes the bulk lattice parameter." if vacancy_enabled
                                 else "Calculated pristine W lattice parameter from S4; the experimental comparator is 3.165 Å."),
        }
    return None, {"reason": "No paper-supported lattice parameter is available for this host/composition."}


def _w_vacancy_occupancy_profiles(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build occupancy profiles only from the matching S7 workbook rows."""
    frequency_data = PAPER_RUNTIME_VALUES["w_vacancy_attempt_frequencies"]
    frequency_by_occupancy = {
        j: frequency_data["values_Hz"][j - 1]
        for j in range(1, len(frequency_data["values_Hz"]) + 1)
    }

    def find(parameter: str, occupancy: int) -> Optional[Dict[str, Any]]:
        expected_configuration = f"{occupancy} H atoms in vacancy"
        return next((row for row in records
                     if row.get("Source ID") == "S7"
                     and row.get("Host") == "W"
                     and row.get("Phase") == "bcc W"
                     and row.get("Interstitial") == "H"
                     and row.get("Parameter") == parameter
                     and str(row.get("Configuration", "")).strip() == expected_configuration
                     and row.get("Status") == "PAPER_REPORTED"
                     and row.get("Unit") == "eV"
                     and isinstance(row.get("Numeric value"), (int, float))
                     and math.isfinite(float(row["Numeric value"]))), None)

    profiles: List[Dict[str, Any]] = []
    for occupancy in range(1, 13):
        binding_dft = find("Incremental H binding e_b,j (DFT)", occupancy)
        binding_zpe = find("Incremental H binding e_b,j (ZPE corrected)", occupancy)
        detrap_dft = find("De-trapping barrier (DFT)", occupancy)
        detrap_zpe = find("De-trapping barrier (ZPE corrected)", occupancy)

        def value(row: Optional[Dict[str, Any]]) -> Optional[float]:
            return float(row["Numeric value"]) if row else None

        b_dft, b_zpe = value(binding_dft), value(binding_zpe)
        d_dft, d_zpe = value(detrap_dft), value(detrap_zpe)
        nu = frequency_by_occupancy.get(occupancy)
        profiles.append({
            "occupancy_j": occupancy,
            "binding_DFT_eV": b_dft,
            "binding_ZPE_eV": b_zpe,
            "detrapping_DFT_eV": d_dft,
            "detrapping_ZPE_eV": d_zpe,
            "capture_saddle_DFT_eV": (b_dft + d_dft) if b_dft is not None and d_dft is not None else None,
            "capture_saddle_ZPE_eV": (b_zpe + d_zpe) if b_zpe is not None and d_zpe is not None else None,
            "attempt_frequency_Hz": nu,
            "attempt_frequency_source": (frequency_data if nu is not None else None),
            "energy_source": "S7 Table 3/Table 4; printed pp. 312–313",
        })
    return profiles


def resolve_lattice_parameter(setup: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the lattice parameter before the frontend constructs its domain."""
    value, record = _paper_lattice_parameter(setup)
    return {"lattice_parameter_A": value, "lattice_parameter_resolution": record}


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
    occupancy_profiles = (
        _w_vacancy_occupancy_profiles(records)
        if host == "W" and structure == "BCC" and species == "H" else []
    )
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
        "w_vacancy_occupancy_profiles": occupancy_profiles,
        "lattice_parameter_A": lattice_a,
        "lattice_parameter_resolution": lattice_record,
        "values": values,
        "missing": missing,
        "non_paper_model_rules": [
            "The engine uses its existing boundary-exit rule: surface and bulk exit barriers fall back to the resolved host migration barrier. This is a solver rule, not a paper-reported boundary transition value.",
            "Attempt frequency, Boltzmann constant, geometry cutoffs, and numerical floors remain solver constants outside the paper-energy database.",
        ],
    }
