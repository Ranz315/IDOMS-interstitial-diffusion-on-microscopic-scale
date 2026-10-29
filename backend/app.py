from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Literal
from engine import run_simulation
from energetics import EnergeticsDatabaseError, load_energy_records, resolve_energy_inputs

VERSION = "0.4-paper-energy-database"

app = FastAPI(title="IDOMS Two-Alloy Backend", version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Domain(BaseModel):
    Nx: int
    Ny: int
    Nz: int
    unit: str
    total_lattice_sites: int
    required_lattice_sites_minimum: int
    physical_size_nm: Dict[str, float]
    estimated_atom_counts: Dict[str, int]

class ToolSetup(BaseModel):
    host: str
    alloying_elements: List[str] = Field(default_factory=list, max_length=2)
    composition_at_percent: Dict[str, float] = Field(default_factory=dict)
    host_at_percent: float
    crystal_structure: Literal["BCC", "FCC"]
    lattice_parameter_A: float
    interstitial_species: Literal["H", "D", "T", "C", "N", "O"]
    site_network: Literal["auto", "tetrahedral", "octahedral", "tetra_octa"] = "auto"
    temperature_K: float
    requested_slab_thickness_nm: float
    boundary: Literal["surface_return", "bulk_transmission", "retention"]
    site_per_unit_cell: int
    domain: Domain

class SimulationInput(BaseModel):
    setup: ToolSetup

@app.get("/health")
def health():
    try:
        record_count = len(load_energy_records())
        database_status = "ready"
    except EnergeticsDatabaseError:
        record_count = 0
        database_status = "unavailable"
    return {"status": "ok" if database_status == "ready" else "degraded",
            "version": VERSION,
            "energetics_database": "IDOMS_Master_Energetics_Database.xlsx",
            "energetics_database_status": database_status,
            "energy_record_count": record_count}

@app.post("/resolve-energies")
def resolve_energies(inp: SimulationInput):
    try:
        return resolve_energy_inputs(inp.setup.model_dump())
    except EnergeticsDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/simulate")
def simulate(inp: SimulationInput):
    if len(inp.setup.alloying_elements) > 2:
        raise HTTPException(status_code=422, detail="This version supports at most two alloying elements.")
    setup = inp.setup.model_dump()
    try:
        resolution = resolve_energy_inputs(setup)
    except EnergeticsDatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not resolution["runnable"]:
        raise HTTPException(status_code=422, detail={
            "message": "Required paper-supported energy values are missing; simulation was not run.",
            "energy_resolution": resolution,
        })
    result = run_simulation(setup, resolution["resolved_energies_eV"])
    result["energy_resolution"] = resolution
    return result
