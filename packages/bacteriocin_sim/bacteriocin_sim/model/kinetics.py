"""Population kinetics: coupled peptide/target ODEs integrated to the readout.

State variables
---------------
``P``   total active peptide concentration (uM)
``Ns``  susceptible viable target population (CFU/mL)
``Nr``  pre-existing tolerant subpopulation (CFU/mL)

Dynamics
--------
    free peptide          C = Langmuir(P, sites(Ns+Nr), Kd)      quasi-equilibrium
    occupancy             theta = C^h / (C^h + MIC_eff^h)        cooperative Hill
    kill rate             k = k_max * theta * phase_susceptibility
    dP/dt  = -k_deg * P + production(producer_density, t)
    dNs/dt = mu(N) * Ns - k * Ns
    dNr/dt = mu(N) * Nr - k * rho * Nr
    mu(N)  = mu_max * f_T * f_pH * richness * (1 - N/Nmax)

The same system is integrated a second time with ``P = 0`` to give the
untreated control, because the reported observables are *relative to a
control* exactly as a real growth-inhibition assay is.

Why an ODE rather than a closed-form dose-response: peptide depletion,
target regrowth and the inoculum effect are coupled in time. A static Hill
curve cannot produce the regrowth-after-partial-kill behaviour that makes
incubation time a genuinely informative experimental variable, and it is that
behaviour that lets a result change the loop's next decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import environment as env
from .parameters import ParameterStore


@dataclass
class KineticsInput:
    mic_um: float
    hill_coefficient: float
    initial_peptide_um: float
    initial_density_cfu_per_ml: float
    producer_density_cfu_per_ml: float
    decay_rate_per_h: float
    mu_max_per_h: float
    growth_factor: float           # f_T * f_pH * medium richness, in [0, 1]
    phase_susceptibility: float
    phase_rate_factor: float
    incubation_time_h: float
    carrying_capacity: float
    binding_sites_per_cell: float
    kd_um: float
    resistant_fraction: float
    resistant_residual: float
    kill_rate_max_per_h: float
    production_rate_um_per_h: float = 0.0


@dataclass
class KineticsOutput:
    treated_final_cfu_per_ml: float
    control_final_cfu_per_ml: float
    initial_cfu_per_ml: float
    final_free_peptide_um: float
    mean_free_peptide_um: float
    mean_occupancy: float
    peak_kill_rate_per_h: float
    survival_fraction_vs_control: float
    log10_reduction_vs_control: float
    log10_change_from_inoculum: float
    regrowth_detected: bool
    trajectory: list[dict[str, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def hill_occupancy(free_um: float, mic_um: float, h: float) -> float:
    """Cooperative occupancy of the lethal target by free peptide."""
    if free_um <= 0.0:
        return 0.0
    mic = max(mic_um, 1e-12)
    ratio = (free_um / mic) ** h
    if not math.isfinite(ratio):
        return 1.0
    return ratio / (1.0 + ratio)


def _derivatives(
    p_um: float,
    ns: float,
    nr: float,
    k: KineticsInput,
    *,
    treated: bool,
) -> tuple[float, float, float, float, float]:
    """Return ``(dP, dNs, dNr, free_um, occupancy)``."""
    total_cells = max(ns + nr, 0.0)
    if treated and p_um > 0.0:
        sites = env.binding_site_concentration_um(total_cells, k.binding_sites_per_cell)
        free = env.free_concentration_um(p_um, sites, k.kd_um)
        occ = hill_occupancy(free, k.mic_um, k.hill_coefficient)
    else:
        free = 0.0
        occ = 0.0

    kill = occ * k.phase_susceptibility * k.kill_rate_max_per_h

    mu = (
        k.mu_max_per_h
        * k.growth_factor
        * k.phase_rate_factor
        * max(0.0, 1.0 - total_cells / max(k.carrying_capacity, 1.0))
    )

    d_p = -k.decay_rate_per_h * p_um + (k.production_rate_um_per_h if treated else 0.0)
    d_ns = mu * ns - kill * ns
    d_nr = mu * nr - kill * k.resistant_residual * nr
    return d_p, d_ns, d_nr, free, occ


def integrate(k: KineticsInput, store: ParameterStore) -> KineticsOutput:
    """Integrate treated and control populations with fixed-step RK4.

    The step count is derived deterministically from the incubation time
    (minimum 200 steps, ~50 steps/h, capped at 4000) so the result is
    bit-identical across runs and platforms for the same input.
    """
    t_end = max(k.incubation_time_h, 0.0)
    warnings: list[str] = []
    n_steps = int(min(4000, max(200, round(t_end * 50))))
    if t_end == 0.0:
        n_steps = 1
    dt = (t_end / n_steps) if n_steps else 0.0

    n0 = max(k.initial_density_cfu_per_ml, 0.0)
    nr0 = n0 * k.resistant_fraction
    ns0 = max(n0 - nr0, 0.0)

    state_t = [k.initial_peptide_um, ns0, nr0]
    state_c = [0.0, ns0, nr0]

    free_sum = 0.0
    occ_sum = 0.0
    samples = 0
    peak_kill = 0.0
    trajectory: list[dict[str, float]] = []
    min_treated_total = ns0 + nr0
    record_every = max(1, n_steps // 24)

    def rk4(state: list[float], treated: bool) -> tuple[list[float], float, float]:
        p0, s0, r0 = state
        d1 = _derivatives(p0, s0, r0, k, treated=treated)
        d2 = _derivatives(
            max(p0 + 0.5 * dt * d1[0], 0.0),
            max(s0 + 0.5 * dt * d1[1], 0.0),
            max(r0 + 0.5 * dt * d1[2], 0.0),
            k, treated=treated,
        )
        d3 = _derivatives(
            max(p0 + 0.5 * dt * d2[0], 0.0),
            max(s0 + 0.5 * dt * d2[1], 0.0),
            max(r0 + 0.5 * dt * d2[2], 0.0),
            k, treated=treated,
        )
        d4 = _derivatives(
            max(p0 + dt * d3[0], 0.0),
            max(s0 + dt * d3[1], 0.0),
            max(r0 + dt * d3[2], 0.0),
            k, treated=treated,
        )
        new = [
            max(p0 + dt / 6.0 * (d1[0] + 2 * d2[0] + 2 * d3[0] + d4[0]), 0.0),
            max(s0 + dt / 6.0 * (d1[1] + 2 * d2[1] + 2 * d3[1] + d4[1]), 0.0),
            max(r0 + dt / 6.0 * (d1[2] + 2 * d2[2] + 2 * d3[2] + d4[2]), 0.0),
        ]
        return new, d1[3], d1[4]

    # t = 0 sample
    _, free0, occ0 = rk4(list(state_t), True) if dt > 0 else (state_t, 0.0, 0.0)
    if dt == 0.0:
        sites = env.binding_site_concentration_um(ns0 + nr0, k.binding_sites_per_cell)
        free0 = env.free_concentration_um(k.initial_peptide_um, sites, k.kd_um)
        occ0 = hill_occupancy(free0, k.mic_um, k.hill_coefficient)

    for step in range(n_steps):
        if dt > 0.0:
            state_t, free, occ = rk4(state_t, True)
            state_c, _, _ = rk4(state_c, False)
        else:
            free, occ = free0, occ0
        free_sum += free
        occ_sum += occ
        samples += 1
        peak_kill = max(peak_kill, occ * k.phase_susceptibility * k.kill_rate_max_per_h)
        total_t = state_t[1] + state_t[2]
        min_treated_total = min(min_treated_total, total_t)
        if step % record_every == 0 or step == n_steps - 1:
            trajectory.append(
                {
                    "time_h": round((step + 1) * dt, 4),
                    "peptide_total_um": round(state_t[0], 6),
                    "free_peptide_um": round(free, 6),
                    "occupancy": round(occ, 6),
                    "treated_cfu_per_ml": total_t,
                    "control_cfu_per_ml": state_c[1] + state_c[2],
                }
            )
        if not all(math.isfinite(v) for v in state_t + state_c):
            warnings.append("numerical instability detected; integration truncated")
            break

    treated_final = max(state_t[1] + state_t[2], 0.0)
    control_final = max(state_c[1] + state_c[2], 0.0)
    if dt == 0.0:
        treated_final = control_final = ns0 + nr0

    # Floor at a single cell per mL: below that, extinction is the meaningful
    # statement and the deterministic ODE is no longer a valid description.
    detection_floor = 1.0
    if 0.0 < treated_final < detection_floor:
        warnings.append(
            "predicted survivor density fell below 1 CFU/mL; the deterministic "
            "population model is not valid at single-cell counts and the value was "
            "floored (interpret as 'complete kill predicted')"
        )
        treated_final = detection_floor

    survival = treated_final / control_final if control_final > 0 else 1.0
    survival = min(1.0, max(0.0, survival))

    log_red = (
        math.log10(control_final / treated_final)
        if treated_final > 0 and control_final > 0
        else 0.0
    )
    log_change = (
        math.log10(treated_final / n0) if n0 > 0 and treated_final > 0 else 0.0
    )
    # Regrowth means the treated population genuinely declined and then
    # recovered -- not merely that an untreated culture grew.
    declined = min_treated_total < 0.5 * n0 if n0 > 0 else False
    regrowth = declined and min_treated_total > 0 and treated_final > 10.0 * min_treated_total

    if 0.0 < nr0 < 1.0:
        warnings.append(
            f"the assumed tolerant subpopulation is {nr0:.3g} cells/mL, i.e. fewer than "
            "one cell in the inoculum; the deterministic result is an expectation over "
            "replicate cultures, not a single realisable culture"
        )

    return KineticsOutput(
        treated_final_cfu_per_ml=treated_final,
        control_final_cfu_per_ml=control_final,
        initial_cfu_per_ml=n0,
        final_free_peptide_um=(
            trajectory[-1]["free_peptide_um"] if (dt > 0.0 and trajectory) else free0
        ),
        mean_free_peptide_um=(free_sum / samples) if samples else free0,
        mean_occupancy=(occ_sum / samples) if samples else occ0,
        peak_kill_rate_per_h=peak_kill,
        survival_fraction_vs_control=survival,
        log10_reduction_vs_control=log_red,
        log10_change_from_inoculum=log_change,
        regrowth_detected=regrowth,
        trajectory=trajectory,
        warnings=warnings,
    )
