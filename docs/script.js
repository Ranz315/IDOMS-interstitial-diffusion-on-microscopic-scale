const DEFAULT_BACKEND_URL = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? "http://localhost:8001"
  : "https://idoms-backend.onrender.com";
const MAX_ALLOY_ELEMENTS = 2;
const MIN_ATOMS_PER_ALLOY = 4;
const MIN_NX_NY = 5;
const MIN_NZ = 8;

const INFERNO = "Inferno";
const TEAL = "#0f766e";

let latestSetup = null;
let latestEnergyResolution = null;
let latestResult = null;

document.addEventListener("DOMContentLoaded", () => {
  // sidebar navigation
  document.querySelectorAll(".nav-link").forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      showView(link.dataset.view);
    });
  });
  document.getElementById("hostElement")?.addEventListener("change", onHostChanged);
  document.getElementById("interstitialSpecies")?.addEventListener("change", updateVacancyAvailability);
  document.getElementById("crystalStructure")?.addEventListener("change", updateVacancyAvailability);
  document.getElementById("vacancyOccupancySelect")?.addEventListener("change", () => renderVacancyTransitionProfile(latestEnergyResolution));
  document.getElementById("vacancyEnergyBasis")?.addEventListener("change", () => renderVacancyTransitionProfile(latestEnergyResolution));
  // Start with the paper-supported pure BCC Fe–H baseline. Alloying elements
  // can be added; unsupported energy combinations will be shown as missing.
  updateAlloyingElementOptions();
  updateLatticeParameter();
  updateVacancyAvailability();
  updateCompositionSummary();
  updateAddButtonState();
});

function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === `view-${name}`));
  document.querySelectorAll(".nav-link").forEach(a => a.classList.toggle("active", a.dataset.view === name));
  window.scrollTo(0, 0);
  // Plotly plots created while their view was hidden need a resize once shown
  if (name === "home" && window.Plotly) {
    ["pathPlot", "barrierPlot", "survivalPlot", "survivalMapPlot"].forEach(id => {
      const el = document.getElementById(id);
      if (el && el.data) Plotly.Plots.resize(el);
    });
  }
}

function apiBase() {
  const el = document.getElementById("backendUrl");
  const v = el ? el.value.trim().replace(/\/$/, "") : "";
  return v || DEFAULT_BACKEND_URL;
}

async function checkBackend() {
  const status = document.getElementById("backendStatus");
  if (!status) return;
  try {
    const r = await fetch(`${apiBase()}/health`);
    const j = await r.json();
    status.textContent = `Backend status: ${j.status}. Version: ${j.version || "unknown"}. Paper database: ${j.energetics_database_status || "unavailable"} (${j.energy_record_count || 0} records).`;
  } catch (err) {
    status.textContent = `Backend check failed: ${err.message}`;
  }
}

function updateAddButtonState() {
  const btn = document.getElementById("addAlloyBtn");
  if (!btn) return;
  const rows = document.querySelectorAll("#compositionRows tr").length;
  btn.style.display = rows >= Math.min(MAX_ALLOY_ELEMENTS, availableAlloyingElements().length) ? "none" : "";
}

function availableAlloyingElements() {
  const host = document.getElementById("hostElement")?.value || "Fe";
  return host === "Fe" ? ["C", "Cr"] : [];
}

function updateAlloyingElementOptions() {
  const rows = [...document.querySelectorAll("#compositionRows tr")];
  const allowed = availableAlloyingElements();
  const chosen = rows.map(row => row.querySelector(".el-symbol")?.value || "").filter(Boolean);
  rows.forEach((row, index) => {
    const select = row.querySelector(".el-symbol");
    const current = select.value;
    const occupied = new Set(chosen.filter((el, i) => i !== index));
    select.innerHTML = '<option value="">Select element</option>' +
      allowed.filter(el => !occupied.has(el) || el === current).map(el => `<option value="${el}">${el}</option>`).join("");
    select.value = current;
  });
  updateAddButtonState();
}

function onHostChanged() {
  document.getElementById("compositionRows").innerHTML = "";
  updateAlloyingElementOptions();
  updateLatticeParameter();
  updateVacancyAvailability();
  updateCompositionSummary();
}

function handleCompositionChange() {
  updateAlloyingElementOptions();
  updateLatticeParameter();
  updateCompositionSummary();
}

function addCompositionRow(element = "", atpct = "") {
  const tbody = document.getElementById("compositionRows");
  if (tbody.children.length >= Math.min(MAX_ALLOY_ELEMENTS, availableAlloyingElements().length)) {
    updateAddButtonState();
    return;
  }
  const tr = document.createElement("tr");
  const available = availableAlloyingElements();
  const chosen = new Set([...tbody.querySelectorAll(".el-symbol")].map(select => select.value).filter(Boolean));
  const options = available.filter(el => !chosen.has(el) || el === element);
  tr.innerHTML = `
    <td><select class="el-symbol" onchange="handleCompositionChange()"><option value="">Select element</option>${options.map(el => `<option value="${el}">${el}</option>`).join("")}</select></td>
    <td><input class="el-atpct" type="number" min="0" max="100" step="0.001" value="${atpct}" oninput="updateCompositionSummary()" /></td>
    <td><button class="remove-btn" onclick="removeRow(this)">Remove</button></td>`;
  tbody.appendChild(tr);
  tr.querySelector(".el-symbol").value = element;
  tr.querySelector(".el-atpct").addEventListener("input", () => {
    updateLatticeParameter();
    updateCompositionSummary();
  });
  updateCompositionSummary();
  updateLatticeParameter();
  updateAddButtonState();
}

function removeRow(btn) {
  btn.closest("tr").remove();
  updateAlloyingElementOptions();
  updateLatticeParameter();
  updateCompositionSummary();
  updateAddButtonState();
}

function getComposition() {
  const rows = [...document.querySelectorAll("#compositionRows tr")];
  const comp = {};
  for (const row of rows) {
    const el = row.querySelector(".el-symbol").value.trim();
    const val = Number(row.querySelector(".el-atpct").value);
    if (el && val > 0) comp[el] = val;
  }
  return comp;
}

function paperLatticeParameter(host, composition) {
  if (host === "Fe") {
    const unsupported = Object.keys(composition).some(el => !["Cr", "C"].includes(el));
    if (unsupported) return {value: null, reason: "MISSING: the current lattice resolver supports Fe–Cr–C only."};
    if (Number(composition.C || 0) > 0) return {value: null, reason: "MISSING: the supplied papers do not report a composition-dependent Fe–C–Cr lattice parameter. TCFE15 requires a licensed Thermo-Calc installation."};
    const crPct = Number(composition.Cr || 0);
    const value = 2.83 + (crPct / 100) * (2.84 - 2.83);
    return {value, reason: "S3: binary Fe–Cr interpolation from pure Fe (2.83 Å) and pure Cr (2.84 Å). The paper reports endpoints to 0.01 Å; finer displayed decimals are arithmetic interpolation only."};
  }
  if (host === "W" && Object.keys(composition).length === 0) {
    const vacancyCount = Number(document.getElementById("vacancyConfiguration")?.value || 0);
    return vacancyCount > 0
      ? {value: 3.187, reason: "S7: optimized DFT cell parameter held fixed for its vacancy calculations. This is the source calculation's cell setting, not a uniform lattice change caused by one vacancy."}
      : {value: 3.172, reason: "S4: calculated lattice constant for pristine W (Table I). The paper gives 3.165 Å as the experimental comparator."};
  }
  return {value: null, reason: "MISSING: no matching paper-sourced lattice parameter is available for this composition."};
}

function updateLatticeParameter() {
  const input = document.getElementById("latticeA");
  if (!input) return;
  const host = document.getElementById("hostElement")?.value || "Fe";
  const resolved = paperLatticeParameter(host, getComposition());
  input.value = resolved.value === null ? "" : resolved.value.toFixed(4);
  const status = document.getElementById("latticeStatus");
  if (status) status.textContent = resolved.reason;
}

function updateVacancyAvailability() {
  updateLatticeParameter();
  const host = document.getElementById("hostElement")?.value || "Fe";
  const species = document.getElementById("interstitialSpecies")?.value || "H";
  const crystal = document.getElementById("crystalStructure")?.value || "BCC";
  const selected = Number(document.getElementById("vacancyConfiguration")?.value || 0) > 0;
  const status = document.getElementById("vacancyStatus");
  const positionControls = document.getElementById("vacancyPositionControls");
  const supported = host === "W" && species === "H" && crystal === "BCC";
  if (positionControls) positionControls.hidden = !(selected && supported);
  if (!status) return;
  if (supported) {
    status.textContent = selected
      ? "Supported case: one fixed BCC W monovacancy trapping one dilute mobile H atom. Enter its independent position below."
      : "Vacancy effects are available for BCC W–H. Enable one monovacancy to enter its independent position.";
  } else {
    status.textContent = "The kinetic vacancy model is available only for BCC W–H. Fe vacancy binding is in the database, but the supplied Fe paper does not report the matching transition barriers.";
  }
}

function updateCompositionSummary() {
  const comp = getComposition();
  const totalAlloy = Object.values(comp).reduce((a, b) => a + b, 0);
  const host = document.getElementById("hostElement")?.value?.trim() || "Host";
  const hostPct = 100 - totalAlloy;
  const box = document.getElementById("compositionSummary");
  if (!box) return;
  if (hostPct < 0) {
    box.textContent = "Error: total alloying content exceeds 100 at.%.";
    return;
  }
  box.textContent =
    `Alloying elements: ${Object.keys(comp).length} / ${Math.min(MAX_ALLOY_ELEMENTS, availableAlloyingElements().length)} available for ${host}\n` +
    `Total alloying content: ${totalAlloy.toFixed(3)} at.%\n` +
    `${host} content: ${hostPct.toFixed(3)} at.%`;
}

function collectSetup(latticeValue = null) {
  const host = document.getElementById("hostElement").value.trim();
  const composition = getComposition();
  const alloyingElements = Object.keys(composition);
  const totalAlloy = Object.values(composition).reduce((a, b) => a + b, 0);
  if (!host) throw new Error("Please enter a host element.");
  if (alloyingElements.length > MAX_ALLOY_ELEMENTS) throw new Error("Maximum 2 alloying elements allowed.");
  if (totalAlloy >= 100) throw new Error("Total alloying content must be less than 100 at.%.");
  const crystal = document.getElementById("crystalStructure").value;
  const vacancyCount = Number(document.getElementById("vacancyConfiguration").value);
  const lattice = latticeValue > 0
    ? {value: latticeValue, reason: "Lattice parameter resolved by the backend for this composition and temperature."}
    : paperLatticeParameter(host, composition);
  if (crystal !== "BCC" || !(lattice.value > 0)) throw new Error(lattice.reason);
  const aAng = lattice.value;
  const temperatureK = Number(document.getElementById("temperatureK").value);
  if (!(temperatureK > 0)) throw new Error("Please enter a valid temperature in K.");
  const slabThicknessNm = Number(document.getElementById("slabThicknessNm").value);
  if (!(slabThicknessNm > 0)) throw new Error("Please enter a valid slab thickness in nm.");
  const sitePerCell = crystal === "BCC" ? 2 : 4;
  const domain = calculateEfficientDomain(composition, crystal, aAng, slabThicknessNm);
  if (vacancyCount && (host !== "W" || crystal !== "BCC" || document.getElementById("interstitialSpecies").value !== "H")) {
    throw new Error("The paper-supported vacancy simulation currently requires BCC W–H.");
  }
  const rawInjection = ["injectionX", "injectionY", "injectionZ"].map(id => document.getElementById(id).value.trim());
  const hasInjectionCoordinate = rawInjection.some(value => value !== "");
  let injectionPosition = {};
  if (hasInjectionCoordinate) {
    if (rawInjection.some(value => value === "" || !Number.isFinite(Number(value)))) {
      throw new Error("Enter all three injection coordinates (x/a, y/a, z/a), or leave all three blank.");
    }
    const coords = rawInjection.map(Number);
    const limits = [domain.Nx, domain.Ny, domain.Nz];
    if (coords.some((value, i) => value < 0 || value > limits[i])) {
      throw new Error(`Injection coordinates must be inside the domain: x/a 0–${domain.Nx}, y/a 0–${domain.Ny}, z/a 0–${domain.Nz}.`);
    }
    injectionPosition = {x: coords[0], y: coords[1], z: coords[2]};
  }
  let vacancyPosition = {};
  if (vacancyCount) {
    const rawVacancy = ["vacancyX", "vacancyY", "vacancyZ"].map(id => document.getElementById(id).value.trim());
    if (rawVacancy.some(value => value === "" || !Number.isFinite(Number(value)))) {
      throw new Error("Enter all three independent vacancy coordinates (x/a, y/a, z/a) when a vacancy is enabled.");
    }
    const coords = rawVacancy.map(Number);
    const limits = [domain.Nx, domain.Ny, domain.Nz];
    if (coords.some((value, i) => value < 0 || value > limits[i])) {
      throw new Error(`Vacancy coordinates must be inside the domain: x/a 0–${domain.Nx}, y/a 0–${domain.Ny}, z/a 0–${domain.Nz}.`);
    }
    vacancyPosition = {x: coords[0], y: coords[1], z: coords[2]};
  }
  return {
    host,
    alloying_elements: alloyingElements,
    composition_at_percent: composition,
    host_at_percent: 100 - totalAlloy,
    crystal_structure: crystal,
    lattice_parameter_A: aAng,
    vacancy_count: vacancyCount,
    injection_position_fractional: injectionPosition,
    vacancy_position_fractional: vacancyPosition,
    interstitial_species: document.getElementById("interstitialSpecies").value,
    site_network: document.getElementById("siteNetwork").value,
    temperature_K: temperatureK,
    requested_slab_thickness_nm: slabThicknessNm,
    boundary: document.getElementById("boundaryType").value,
    site_per_unit_cell: sitePerCell,
    domain
  };
}

function calculateEfficientDomain(composition, crystal, aAng, slabThicknessNm) {
  const sitePerCell = crystal === "BCC" ? 2 : 4;
  const fractions = Object.values(composition).filter(v => v > 0).map(v => v / 100);
  let requiredLatticeSites = 160;
  for (const f of fractions) requiredLatticeSites = Math.max(requiredLatticeSites, Math.ceil(MIN_ATOMS_PER_ALLOY / f));
  const aNm = aAng * 0.1;
  let Nz = Math.max(MIN_NZ, Math.ceil(slabThicknessNm / aNm));
  const requiredCells = Math.ceil(requiredLatticeSites / sitePerCell);
  let Nx = Math.max(MIN_NX_NY, Math.ceil(Math.sqrt(requiredCells / Nz)));
  let Ny = Nx;
  while (sitePerCell * Nx * Ny * Nz < requiredLatticeSites) {
    if (Nx <= Ny) Nx++; else Ny++;
  }
  const totalSites = sitePerCell * Nx * Ny * Nz;
  const atomCounts = {};
  for (const [el, atpct] of Object.entries(composition)) atomCounts[el] = Math.max(1, Math.round(totalSites * atpct / 100));
  const totalAlloyAtoms = Object.values(atomCounts).reduce((a, b) => a + b, 0);
  atomCounts["host"] = Math.max(0, totalSites - totalAlloyAtoms);
  return {
    Nx, Ny, Nz,
    unit: "unit cells",
    total_lattice_sites: totalSites,
    required_lattice_sites_minimum: requiredLatticeSites,
    physical_size_nm: {Lx: Nx * aNm, Ly: Ny * aNm, Lz: Nz * aNm},
    estimated_atom_counts: atomCounts
  };
}

async function prepareEnergyInputs() {
  try {
    latestSetup = null;
    latestEnergyResolution = null;
    const host = document.getElementById("hostElement").value.trim();
    const composition = getComposition();
    const temperatureK = Number(document.getElementById("temperatureK").value);
    if (!(temperatureK > 0)) throw new Error("Please enter a valid temperature in K.");
    const latticeResponse = await fetch(`${apiBase()}/resolve-lattice`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        host,
        composition_at_percent: composition,
        crystal_structure: document.getElementById("crystalStructure").value,
        temperature_K: temperatureK,
        vacancy_count: Number(document.getElementById("vacancyConfiguration").value)
      })
    });
    const latticeData = await latticeResponse.json();
    if (!latticeResponse.ok) throw new Error(typeof latticeData.detail === "string" ? latticeData.detail : JSON.stringify(latticeData.detail || latticeData));
    if (!(latticeData.lattice_parameter_A > 0)) {
      const reason = latticeData.lattice_parameter_resolution?.reason || "The lattice parameter is missing for this composition.";
      const detail = latticeData.lattice_parameter_resolution?.detail;
      throw new Error(detail ? `${reason}\n${detail}` : reason);
    }
    latestSetup = collectSetup(latticeData.lattice_parameter_A);
    const latticeInput = document.getElementById("latticeA");
    if (latticeInput) latticeInput.value = Number(latticeData.lattice_parameter_A).toFixed(4);
    const latticeStatus = document.getElementById("latticeStatus");
    if (latticeStatus) {
      const lr = latticeData.lattice_parameter_resolution || {};
      latticeStatus.textContent = lr.paper_location || lr.mapping_or_limit || "Lattice parameter resolved from the available source records.";
    }
    latestEnergyResolution = null;
    const d = latestSetup.domain;
    const L = d.physical_size_nm;
    const counts = Object.entries(d.estimated_atom_counts).map(([k, v]) => `${k}: ${v}`).join(", ");
    const injectionText = Object.keys(latestSetup.injection_position_fractional).length
      ? Object.values(latestSetup.injection_position_fractional).map(v => Number(v).toFixed(2)).join(", ")
      : "automatic source distribution";
    const vacancyText = latestSetup.vacancy_count
      ? Object.values(latestSetup.vacancy_position_fractional).map(v => Number(v).toFixed(2)).join(", ") + " (requested x/a, y/a, z/a; snaps to nearest W site)"
      : "none";
    document.getElementById("domainSummary").textContent =
      `Calculated domain: ${d.Nx} × ${d.Ny} × ${d.Nz} ${d.unit}\n` +
      `Physical size: ${L.Lx.toFixed(3)} × ${L.Ly.toFixed(3)} × ${L.Lz.toFixed(3)} nm\n` +
      `Total lattice sites: ${d.total_lattice_sites}\n` +
      `Estimated lattice-site counts: ${counts}\n` +
      `Vacancies included: ${latestSetup.vacancy_count ? "one isolated monovacancy" : "none"}\n` +
      `H injection (x/a, y/a, z/a): ${injectionText}\n` +
      `Independent vacancy position: ${vacancyText}\n` +
      `Resolved lattice parameter: ${latestSetup.lattice_parameter_A.toFixed(4)} Å\n\n` +
      `Nx, Ny and Nz are numbers of unit cells. Physical length is N × a.`;
    document.getElementById("runStatus").textContent = "Looking up paper-supported energy values...";
    const response = await fetch(`${apiBase()}/resolve-energies`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({setup: latestSetup})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
    latestEnergyResolution = data;
    renderEnergyFields(data);
    renderVacancyTransitionProfile(data);
    document.getElementById("runStatus").textContent = data.runnable
      ? "Paper-supported energy values are ready."
      : "Simulation blocked: one or more required paper values are missing.";
  } catch (err) { alert(err.message); }
}

function renderVacancyTransitionProfile(resolution) {
  const card = document.getElementById("vacancyEnergyCard");
  const note = document.getElementById("vacancyEnergyNote");
  const plot = document.getElementById("vacancyEnergyPlot");
  if (!card || !note || !plot) return;
  const supported = latestSetup?.host === "W" && latestSetup?.crystal_structure === "BCC" &&
    latestSetup?.interstitial_species === "H" && Number(latestSetup?.vacancy_count) === 1;
  card.hidden = !supported;
  if (!supported) {
    if (window.Plotly) {
      Plotly.purge(plot);
    }
    return;
  }

  const profiles = resolution?.w_vacancy_occupancy_profiles || [];
  const select = document.getElementById("vacancyOccupancySelect");
  const basisSelect = document.getElementById("vacancyEnergyBasis");
  if (!profiles.length || !select || !basisSelect) {
    note.textContent = "MISSING: occupancy-specific S7 records were not resolved; no profile is drawn.";
    Plotly.purge(plot);
    return;
  }

  const previous = select.value || "1";
  select.innerHTML = profiles.map(p => `<option value="${p.occupancy_j}">j = ${p.occupancy_j}</option>`).join("");
  select.value = profiles.some(p => String(p.occupancy_j) === previous) ? previous : "1";
  const occupancy = Number(select.value);
  const profile = profiles.find(p => p.occupancy_j === occupancy);
  const basis = basisSelect.value === "ZPE" ? "ZPE" : "DFT";
  const binding = profile?.[`binding_${basis}_eV`];
  const capture = profile?.[`capture_saddle_${basis}_eV`];
  const detrapping = profile?.[`detrapping_${basis}_eV`];
  if (![binding, capture, detrapping].every(Number.isFinite)) {
    note.textContent = `MISSING: S7 ${basis} energy values are incomplete for occupancy j=${occupancy}.`;
    Plotly.purge(plot);
    return;
  }

  const before = occupancy === 1 ? "H + empty vacancy" : `H + V H${occupancy - 1}`;
  const inside = `V H${occupancy}`;
  note.textContent = `S7 ${basis} values for occupancy j=${occupancy}: binding ${binding.toFixed(2)} eV; detrapping barrier ${detrapping.toFixed(2)} eV; capture saddle ${capture.toFixed(2)} eV (derived from the paper energy relation). The transport result above still uses the single-H vacancy model.`;
  const labels = [before, "Capture saddle", inside, "Detrapping saddle", before];
  const energies = [0, capture, binding, capture, 0];
  const traces = [{
    x: [0, 1, 2, 3, 4], y: energies,
    mode: "lines+markers+text", type: "scatter", name: `S7 occupancy j=${occupancy}`,
    text: ["0 eV", `+${capture.toFixed(2)} eV`, `${binding.toFixed(2)} eV`, `+${capture.toFixed(2)} eV`, "0 eV"],
    textposition: ["bottom center", "top center", "bottom center", "top center", "bottom center"],
    line: {color: TEAL, width: 3}, marker: {size: 10, color: ["#0284c7", "#dc2626", "#7c3aed", "#dc2626", "#0284c7"]}
  }];
  Plotly.newPlot(plot, traces, {
    title: `S7 vacancy capture and detrapping energy path (j=${occupancy})`,
    xaxis: {title: "transition coordinate (schematic)", tickmode: "array", tickvals: [0, 1, 2, 3, 4], ticktext: labels},
    yaxis: {title: `energy relative to ${before} (eV)`, range: [Math.min(0, binding) - 0.35, Math.max(0, capture) + 0.55]},
    annotations: [
      {x: 0.5, y: capture + 0.18, showarrow: false, text: `capture ΔE‡ = ${capture.toFixed(2)} eV`, font: {size: 11, color: "#0f766e"}},
      {x: 2.5, y: capture + 0.38, showarrow: false, text: `detrapping ΔE‡ = ${detrapping.toFixed(2)} eV`, font: {size: 11, color: "#b91c1c"}}
    ],
    showlegend: false, margin: {l: 75, r: 30, t: 55, b: 80}
  }, {responsive: true});
}

function renderEnergyFields(resolution) {
  const container = document.getElementById("energyFields");
  container.innerHTML = "";
  (resolution.values || []).forEach(item => {
    const row = document.createElement("div");
    row.className = "energy-row";
    const details = document.createElement("div");
    const label = document.createElement("label");
    label.textContent = item.key;
    const status = document.createElement("span");
    status.className = "energy-type";
    status.textContent = item.status || "UNKNOWN";
    const provenance = document.createElement("div");
    provenance.className = "energy-key";
    provenance.textContent = [item.source_id, item.doi, item.paper_location, item.verification].filter(Boolean).join(" · ")
      || item.reported_value_or_wording || "No matching paper record.";
    details.append(label, status, provenance);
    const value = document.createElement("strong");
    value.className = "energy-value";
    value.textContent = item.value === null || item.value === undefined ? "MISSING" : `${formatValue(item.value)} ${item.unit || ""}`.trim();
    row.append(details, value);
    container.appendChild(row);
  });
  if (resolution.missing?.length) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = "Required paper values missing: " + resolution.missing.map(x => `${x.key} — ${x.reason}`).join("; ");
    container.appendChild(note);
  }
  if (resolution.non_paper_model_rules?.length) {
    const note = document.createElement("p");
    note.className = "energy-key";
    note.textContent = "Solver rules (not paper energy records): " + resolution.non_paper_model_rules.join(" ");
    container.appendChild(note);
  }
}

async function runSimulation() {
  const runButton = document.querySelector('button[onclick="runSimulation()"]');
  if (runButton?.disabled) return;
  if (runButton) {
    runButton.disabled = true;
    runButton.textContent = "Running simulation…";
  }
  try {
    await prepareEnergyInputs();
    if (!latestSetup || !latestEnergyResolution) return;
    if (!latestEnergyResolution.runnable) {
      document.getElementById("runStatus").textContent = "Simulation blocked: required paper values are missing.";
      return;
    }
    const payload = {setup: latestSetup};
    document.getElementById("runStatus").textContent = "Running backend graph/KMC calculation...";
    const response = await fetch(`${apiBase()}/simulate`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    if (!response.ok) throw new Error(`Backend error: ${await response.text()}`);
    latestResult = await response.json();
    if (latestResult && latestResult.error) throw new Error(latestResult.error);
    renderResults(latestResult);
    const survivalMethod = latestResult.survival_output_method || "matrix exponential";
    document.getElementById("runStatus").textContent =
      `Simulation complete using the resolved material energy values. Survival plot method: ${survivalMethod}.`;
  } catch (err) {
    alert(err.message);
    document.getElementById("runStatus").textContent = "Simulation failed.";
  } finally {
    if (runButton) {
      runButton.disabled = false;
      runButton.textContent = "Run backend simulation and visualise pathway";
    }
  }
}

function renderResults(result) {
  renderMetricCards(result.metrics || {});
  renderPathPlot(result);
  renderBarrierPlot(result);
  updateVacancyProfileOutcome(result);
  renderVacancyCaptureMap(result);
  renderSurvivalPlot(result);
  renderSurvivalMapPlot(result);
}

function updateVacancyProfileOutcome(result) {
  const box = document.getElementById("vacancyRunOutcome");
  if (!box) return;
  if (!result.vacancy_configuration?.enabled) {
    box.hidden = true;
    return;
  }
  const capture = result.metrics?.vacancy_capture_probability_before_exit;
  if (!Number.isFinite(capture)) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const routeHitsTrap = result.barrier_profile?.dominant_route_crosses_vacancy_trap;
  const routeText = routeHitsTrap ? "The dominant route passes through the vacancy." : "The dominant route goes around the vacancy.";
  const cfg = result.vacancy_configuration || {};
  const showPosition = p => p ? `(${Number(p.x).toFixed(2)}, ${Number(p.y).toFixed(2)}, ${Number(p.z).toFixed(2)})` : "not reported";
  const hStart = showPosition(cfg.effective_injection_position_fractional);
  const vacancySite = showPosition(cfg.placed_position_fractional?.[0]);
  const hTrap = showPosition(cfg.H1_trap_position_fractional?.[0]);
  const dVacancy = Number.isFinite(cfg.injection_to_vacancy_distance_A) ? `${Number(cfg.injection_to_vacancy_distance_A).toFixed(3)} Å` : "—";
  const dTrap = Number.isFinite(cfg.injection_to_H1_trap_distance_A) ? `${Number(cfg.injection_to_H1_trap_distance_A).toFixed(3)} Å` : "—";
  box.innerHTML = `<div class="capture-outcome-value">${formatValue(100 * capture)}%</div><div class="capture-outcome-label">Chance H reaches the vacancy before it exits</div><div class="capture-outcome-route">${routeText}</div><div class="capture-outcome-geometry">Effective H start (x/a, y/a, z/a): ${hStart} · W vacancy: ${vacancySite} · H₁ trap: ${hTrap}<br>H-start distance to vacancy: ${dVacancy} · to H₁ trap: ${dTrap}</div>`;
}

function renderVacancyCaptureMap(result) {
  const el = document.getElementById("vacancyCapturePlot");
  if (!el) return;
  if (!result.vacancy_configuration?.enabled) {
    Plotly.purge(el);
    return;
  }
  const m = result.vacancy_capture_map || {x: [], z: [], probability: []};
  const domain = result.domain || latestSetup?.domain || {};
  const probability = m.probability || [];
  const sortedCapture = probability.filter(Number.isFinite).slice().sort((a, b) => a - b);
  const scaleMax = Math.max(sortedCapture[Math.floor(0.95 * Math.max(0, sortedCapture.length - 1))] || 0, 1e-9);
  const contrastProbability = probability.map(p => Math.max(0, Math.min(1, p / scaleMax)));
  const captureTicks = [0, 0.25, 0.5, 0.75, 1];
  const traces = [{
    x: m.x || [], y: m.z || [], mode: "markers", type: "scattergl", name: "P(capture before exit)",
    marker: {size: 7, color: contrastProbability,
      colorscale: [[0, "#dceaf0"], [0.2, "#b7d1db"], [0.4, "#8bb5c3"], [0.6, "#5a91a3"], [0.8, "#356779"], [1, "#1b3a4a"]],
      cmin: 0, cmax: 1, opacity: 1, line: {width: 0},
      colorbar: {title: "P(capture<br>before exit)", tickvals: captureTicks, ticktext: captureTicks.map(f => f === 1 ? `≥${(100 * scaleMax).toFixed(1)}%` : `${(100 * scaleMax * f).toFixed(1)}%`)}, symbol: "square"},
    customdata: probability, hovertemplate: "x/a=%{x:.2f}<br>z/a=%{y:.2f}<br>P(capture before exit)=%{customdata:.1%}<extra></extra>"
  }];
  const trap = result.vacancy_trap_points || {x: [], z: []};
  const vacancy = result.vacancy_positions || {x: [], z: []};
  const annotations = [];
  const path = result.dominant_pathway || {};
  const inj = Number.isInteger(path.injection_index) ? path.injection_index : -1;
  if (inj >= 0 && inj < (path.x || []).length) {
    traces.push({x: [path.x[inj]], y: [path.z[inj]], mode: "markers", type: "scatter", name: "Injection", showlegend: false, hoverinfo: "skip", marker: {size: 29, color: "#ffffff", symbol: "circle", line: {width: 2, color: "#ffffff"}}});
    traces.push({x: [path.x[inj]], y: [path.z[inj]], mode: "markers", type: "scatter", name: "Injection", marker: {size: 19, color: "#e69f00", symbol: "star", line: {width: 1.5, color: "#ffffff"}}});
    annotations.push({x: path.x[inj] - 0.12, y: path.z[inj] + 0.28, xanchor: "right", yanchor: "top", text: "Injection", showarrow: false, bgcolor: "rgba(255,255,255,0.96)", bordercolor: "#b78100", borderwidth: 1, borderpad: 3, font: {size: 11, color: "#704f00"}});
  }
  if (vacancy.x?.length && trap.x?.length) {
    traces.push({x: [vacancy.x[0], trap.x[0]], y: [vacancy.z[0], trap.z[0]], mode: "lines", type: "scatter", name: "vacancy-to-H₁ offset (not a hop)", line: {width: 1.5, color: "#b83280", dash: "dot"}, hoverinfo: "skip"});
    traces.push({x: vacancy.x, y: vacancy.z, mode: "markers", type: "scatter", name: "Vacancy (missing W)", marker: {size: 14, color: "#374151", symbol: "x", line: {width: 2.5, color: "#ffffff"}}});
    annotations.push({x: vacancy.x[0] - 0.12, y: vacancy.z[0] - 0.28, xanchor: "right", yanchor: "bottom", text: "W vacancy", showarrow: false, bgcolor: "rgba(255,255,255,0.96)", bordercolor: "#4b5563", borderwidth: 1, borderpad: 3, font: {size: 11, color: "#374151"}});
  }
  if (trap.x?.length) {
    // Draw the vacancy last so it remains visible when it is close to the source.
    // The hollow foreground marker lets both locations remain identifiable if they overlap.
    traces.push({x: trap.x, y: trap.z, mode: "markers", type: "scatter", name: "H₁ trap near vacancy O-site", showlegend: false, hoverinfo: "skip", marker: {size: 27, color: "rgba(255,255,255,0)", symbol: "diamond", line: {width: 5, color: "#ffffff"}}});
    traces.push({x: trap.x, y: trap.z, mode: "markers", type: "scatter", name: "H₁ trap near vacancy O-site", marker: {size: 18, color: "rgba(184,50,128,0)", symbol: "diamond", line: {width: 3, color: "#b83280"}}});
    annotations.push({x: trap.x[0] + 0.12, y: trap.z[0] - 0.28, xanchor: "left", yanchor: "bottom", text: "H₁ trap", showarrow: false, bgcolor: "rgba(255,255,255,0.96)", bordercolor: "#b83280", borderwidth: 1, borderpad: 3, font: {size: 11, color: "#702459"}});
  }
  Plotly.newPlot(el, traces, {
    title: "Site-resolved probability of H reaching the vacancy before exit",
    xaxis: {title: "x / a", range: [0, Math.max(1, Number(domain.Nx) || 1)]},
    yaxis: {title: "depth z / a", range: [Math.max(1, Number(domain.Nz) || 1), 0]},
    annotations,
    legend: {orientation: "h"}, margin: {l: 65, r: 55, t: 55, b: 65}
  }, {responsive: true});
}

function isFiniteArray(arr) { return Array.isArray(arr) && arr.length > 0 && arr.every(v => Number.isFinite(v)); }

function formatValue(v) { if (v === null || v === undefined || Number.isNaN(v)) return "—"; if (Math.abs(v) > 0 && (Math.abs(v) < 1e-3 || Math.abs(v) > 1e4)) return Number(v).toExponential(3); return Number(v).toFixed(4); }

function renderMetricCards(metrics) {
  const container = document.getElementById("metricsCards");
  container.innerHTML = "";
  const labels = {
    mean_first_passage_time_s: "Mean first-passage time (s)", probability_bulk_transmission: "Probability of bulk transmission", probability_surface_return: "Probability of surface return", bottleneck_barrier_eV: "Critical bottleneck barrier (eV)", minimum_resistance_path_s: "Minimum path resistance (s)", path_tortuosity: "Pathway tortuosity", pathway_energy_cost_eV: "Mean activation barrier on dominant path (eV)", vacancy_capture_probability_before_exit: "Chance H reaches vacancy before exit", trap_residence_fraction: "Share of residence time spent in trap", percolation_accessibility_fraction: "Accessible interstitial fraction", retention_factor_vs_host: "Retention factor vs ideal host"};
  for (const [key, label] of Object.entries(labels)) {
    if (!(key in metrics)) continue;
    const div = document.createElement("div");
    div.className = "metric";
    div.innerHTML = `<div class="value">${formatValue(metrics[key])}</div><div class="label">${label}</div>`;
    container.appendChild(div);
  }
}

// ---- Plot (a): lattice-aware minimum-resistance channel -------------------
function soluteStyle(el) {
  if (["C", "N", "O", "B"].includes(el)) return {symbol: "diamond", color: "#ef4444"};
  return {symbol: "triangle-up", color: "#22c55e"};
}

function renderPathPlot(result) {
  const d = result.domain || latestSetup.domain;
  const geometryHint = document.getElementById("vacancyGeometryHint");
  if (geometryHint) geometryHint.hidden = !result.vacancy_configuration?.enabled;
  const traces = [];
  if (result.lattice_points?.x?.length) traces.push({x: result.lattice_points.x, y: result.lattice_points.z, mode: "markers", type: "scatter", name: "host lattice", marker: {size: 4, color: "rgba(100,116,139,0.30)"}});
  if (result.interstitial_sites?.x?.length) traces.push({x: result.interstitial_sites.x, y: result.interstitial_sites.z, mode: "markers", type: "scatter", name: "interstitial sites", marker: {size: 3, color: "rgba(125,211,252,0.35)"}});
  if (result.trap_sites?.x?.length) traces.push({x: result.trap_sites.x, y: result.trap_sites.z, mode: "markers", type: "scatter", name: "trap sites (U<0)", marker: {size: 7, color: "rgba(168,85,247,0.50)", symbol: "circle"}});
  const vac = result.vacancy_positions || {x: [], z: []};
  const hTrap = result.vacancy_trap_points || {x: [], z: []};
  if (vac.x?.length && hTrap.x?.length) traces.push({x: [vac.x[0], hTrap.x[0]], y: [vac.z[0], hTrap.z[0]], mode: "lines", type: "scatter", name: "vacancy to H₁ trap offset", line: {width: 1.5, color: "#b83280", dash: "dot"}, hoverinfo: "skip"});
  if (vac.x?.length) traces.push({x: vac.x, y: vac.z, mode: "markers", type: "scatter", name: "vacancy (missing W)", marker: {size: 12, color: "#111827", symbol: "x", line: {width: 2}}});
  if (hTrap.x?.length) traces.push({x: hTrap.x, y: hTrap.z, mode: "markers", type: "scatter", name: "H₁ trap near vacancy O-site", marker: {size: 10, color: "#a855f7", symbol: "diamond", line: {width: 1, color: "#111"}}});
  if (result.high_barrier_edges?.x?.length) traces.push({x: result.high_barrier_edges.x, y: result.high_barrier_edges.z, mode: "markers", type: "scatter", name: "high-barrier edges (top 5%)", marker: {size: 7, color: "rgba(220,38,38,0.65)", symbol: "x"}});
  const byEl = {};
  for (const s of result.solute_positions || []) {
    if (!byEl[s.element]) byEl[s.element] = {x: [], z: []};
    byEl[s.element].x.push(s.x); byEl[s.element].z.push(s.z);
  }
  for (const [el, pts] of Object.entries(byEl)) {
    const st = soluteStyle(el);
    traces.push({x: pts.x, y: pts.z, mode: "markers", type: "scatter", name: `${el} solute`, marker: {size: 10, symbol: st.symbol, color: st.color, line: {width: 0.5, color: "#111"}, opacity: 0.9}});
  }
  const path = result.dominant_pathway || {x: [], z: [], activation_barrier_eV: []};
  traces.push({x: path.x || [], y: path.z || [], mode: "lines+markers", type: "scatter", name: "minimum-resistance channel", line: {width: 4, color: TEAL}, marker: {size: 7, color: path.activation_barrier_eV || [], colorscale: INFERNO, colorbar: {title: "activation<br>barrier (eV)"}, line: {width: 0.3, color: "#111"}}});
  if (path.x && path.x.length && Number.isInteger(path.injection_index)) {
    const jx = path.x[path.injection_index], jz = path.z[path.injection_index];
    traces.push({x: [jx], y: [jz], mode: "markers", type: "scatter", name: "injection site", marker: {size: 18, symbol: "star", color: "#fde047", line: {width: 0.8, color: "#111"}}});
  }
  if (path.surface_exit) traces.push({x: [path.surface_exit.x], y: [path.surface_exit.z], mode: "markers", type: "scatter", name: "surface exit", marker: {size: 11, symbol: "square", color: "#0ea5e9", line: {width: 0.6, color: "#111"}}});
  if (path.bulk_exit) traces.push({x: [path.bulk_exit.x], y: [path.bulk_exit.z], mode: "markers", type: "scatter", name: "bulk exit", marker: {size: 11, symbol: "square", color: "#7c3aed", line: {width: 0.6, color: "#111"}}});
  Plotly.newPlot("pathPlot", traces, {
    title: "Minimum-resistance channel through injection site (lattice y-slice)",
    xaxis: {title: "x / a", range: [-0.25, d.Nx + 0.25]},
    yaxis: {title: "depth z / a", range: [d.Nz + 0.25, -0.25]},
    legend: {orientation: "h"}, margin: {l: 65, r: 30, t: 55, b: 90}
  }, {responsive: true});
}

// ---- Plot (b): activation-barrier profile along the channel ---------------
function renderBarrierPlot(result) {
  const bp = result.barrier_profile || {jump_index: [], activation_barrier_eV: []};
  const x = bp.jump_index || [], y = bp.activation_barrier_eV || [];
  const traces = [{x, y, mode: "lines+markers", type: "scatter", name: "activation barrier", line: {width: 2.4, color: TEAL}, marker: {size: 6, color: y, colorscale: INFERNO, line: {width: 0.3, color: "#111"}}}];
  if (Number.isInteger(bp.bottleneck_index) && bp.bottleneck_index > 0) {
    const bi = bp.bottleneck_index - 1;
    traces.push({x: [x[bi]], y: [y[bi]], mode: "markers", type: "scatter", name: "bottleneck", marker: {size: 15, symbol: "circle-open", color: "#dc2626", line: {width: 2.2}}});
  }
  const shapes = [];
  const anns = [];
  if (typeof bp.host_barrier_eV === "number") {
    shapes.push({type: "line", xref: "paper", x0: 0, x1: 1, y0: bp.host_barrier_eV, y1: bp.host_barrier_eV, line: {dash: "dash", width: 1.3, color: "#64748b"}});
    anns.push({xref: "paper", x: 0.01, y: bp.host_barrier_eV, yanchor: "bottom", showarrow: false, text: `host barrier Eₘ⁰ = ${bp.host_barrier_eV.toFixed(3)} eV`, font: {size: 11, color: "#475569"}});
  }
  if (Number.isInteger(bp.injection_index) && bp.injection_index > 0 && bp.injection_index < x.length) {
    const jx = bp.injection_index + 0.5;
    shapes.push({type: "line", x0: jx, x1: jx, yref: "paper", y0: 0, y1: 1, line: {dash: "dot", width: 1.2, color: "#f59e0b"}});
    anns.push({x: jx, yref: "paper", y: 0.98, yanchor: "top", showarrow: false, text: "injection", textangle: 90, font: {size: 10, color: "#b45309"}});
  }
  if (result.vacancy_configuration?.enabled && !bp.channel_crosses_vacancy_trap) {
    anns.push({xref: "paper", x: 0.99, y: 0.96, xanchor: "right", yanchor: "top", showarrow: false,
      text: "Selected channel avoids vacancy; trapping affects residence time, not this path profile.",
      font: {size: 10, color: "#475569"}});
  }
  Plotly.newPlot("barrierPlot", traces, {
    title: "Activation-barrier profile along channel (surface → bulk)",
    xaxis: {title: "jump index along channel"},
    yaxis: {title: "activation barrier (eV)"},
    shapes, annotations: anns, showlegend: false, margin: {l: 70, r: 30, t: 55, b: 60}
  }, {responsive: true});
}

// ---- Plot (c): global survival probability --------------------------------
function renderSurvivalPlot(result) {
  let t = result.survival_probability?.time_s || [];
  let s = result.survival_probability?.S_t || [];
  const mfpt = result.survival_probability?.mfpt_s;
  if (!isFiniteArray(t) || !isFiniteArray(s) || t.length !== s.length) { t = [0, 1]; s = [1, 0]; }
  const shapes = [], anns = [];
  if (typeof mfpt === "number" && mfpt > 0) {
    shapes.push({type: "line", x0: mfpt, x1: mfpt, yref: "paper", y0: 0, y1: 1, line: {dash: "dot", width: 1.4, color: "#dc2626"}});
    anns.push({x: mfpt, y: 0.5, xanchor: "left", showarrow: false, text: ` MFPT = ${Number(mfpt).toExponential(2)} s`, font: {size: 11, color: "#991b1b"}});
  }
  const approximate = String(result.survival_output_method || "").includes("approximation");
  Plotly.newPlot("survivalPlot", [{x: t, y: s, mode: "lines", type: "scatter", name: "S(t)", fill: "tozeroy", fillcolor: "rgba(15,118,110,0.08)", line: {width: 3, color: TEAL}}], {
    title: approximate ? "Global survival probability S(t) — MFPT-based approximation" : "Global survival probability S(t)",
    xaxis: {title: "time (s)"}, yaxis: {title: "S(t)", range: [0, 1.05]},
    shapes, annotations: anns, showlegend: false, margin: {l: 65, r: 30, t: 55, b: 60}
  }, {responsive: true});
}

// ---- Plot (d): site-resolved survival map at t = MFPT ---------------------
function renderSurvivalMapPlot(result) {
  const d = result.domain || latestSetup.domain;
  const m = result.survival_map || {x: [], z: [], S: []};
  const traces = m.available === false ? [] : [{
    x: m.x || [], y: m.z || [], mode: "markers", type: "scattergl", name: "S_i(MFPT)",
    marker: {size: 6, color: m.S || [], colorscale: "Viridis", cmin: 0, cmax: 1, colorbar: {title: "P(survive<br>to MFPT)"}, symbol: "square"}
  }];
  const path = result.dominant_pathway;
  if (path?.x?.length) {
    traces.push({x: path.x, y: path.z, mode: "lines", type: "scatter", name: "channel", line: {width: 2.4, color: "#ffffff"}});
    if (Number.isInteger(path.injection_index)) traces.push({x: [path.x[path.injection_index]], y: [path.z[path.injection_index]], mode: "markers", type: "scatter", name: "injection", marker: {size: 15, symbol: "star", color: "#fde047", line: {width: 0.7, color: "#111"}}});
  }
  Plotly.newPlot("survivalMapPlot", traces, {
    title: m.available === false ? "Site-resolved survival map omitted for approximate global curve" : "Site-resolved survival probability at t = MFPT",
    xaxis: {title: "x / a", range: [0, d.Nx]},
    yaxis: {title: "depth z / a", range: [d.Nz, 0]},
    annotations: m.available === false ? [{xref: "paper", yref: "paper", x: 0.5, y: 0.5, showarrow: false,
      text: m.reason || "Not calculated for this run."}] : [],
    legend: {orientation: "h"}, margin: {l: 65, r: 30, t: 55, b: 70}
  }, {responsive: true});
}

function downloadInputJson() { if (!latestSetup) { alert("Calculate the domain and resolve paper values first."); return; } downloadJson("idoms_input.json", {setup: latestSetup, energies_eV: latestEnergyResolution?.resolved_energies_eV || {}, energy_resolution: latestEnergyResolution}); }
function downloadResultJson() { if (!latestResult) { alert("Run a simulation first."); return; } downloadJson("idoms_result.json", latestResult); }
function downloadJson(filename, obj) { const blob = new Blob([JSON.stringify(obj, null, 2)], {type: "application/json"}); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url); }
