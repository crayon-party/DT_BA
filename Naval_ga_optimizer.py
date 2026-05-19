"""
Naval_ga_optimiser.py
=====================
Offline Genetic Algorithm for Naval Berth Allocation.

Optimises four internal parameters of the greedy dispatch fitness function:
  lambda_beta  — fatigue term multiplier       [0.5, 3.0]
  lambda_gamma — delay reward multiplier       [0.5, 3.0]
  lambda_delta — emission reward multiplier    [0.5, 3.0]
  lambda_block — blocking penalty multiplier   [0.5, 3.0]

The greedy simulator (Naval_sim_em_heuristics.py) is treated as a black-box
fitness function. Each chromosome sets these four parameters, runs the full
168h simulation, and returns Z as the fitness score.

Architecture:
  Phase 1 (this file) — GA finds optimal parameter vector offline
  Phase 2             — Digital twin plays back using GA-optimised parameters
  Phase 3             — Greedy rescheduler handles weather events in real time
                        using the same GA-optimised parameters
"""

from __future__ import annotations

import random
import time
from typing import Callable, Dict, List, Optional, Tuple

from Naval_sim_em_heuristics import (
    NavalFinalOptimizer,
    S_REF, F_REF, D_REF, E_REF,
)

# ── GA Hyperparameters ────────────────────────────────────────────────────────
POP_SIZE      = 30
N_GENERATIONS = 50
CROSSOVER_P   = 0.8
MUTATION_P    = 0.2
MUTATION_STD  = 0.2    # Gaussian noise std for mutation
TOURNAMENT_K  = 3
ELITE_N       = 2
CONVERGE_TOL  = 1e-4
CONVERGE_GENS = 10
HORIZON_H     = 168

# ── Parameter bounds ──────────────────────────────────────────────────────────
# chromosome = [lambda_beta, lambda_gamma, lambda_delta, lambda_block]
PARAM_MIN = [0.5, 0.5, 0.5, 0.5]
PARAM_MAX = [3.0, 3.0, 3.0, 3.0]
PARAM_DEFAULT = [1.0, 1.0, 1.0, 1.0]
PARAM_NAMES = ['lambda_beta', 'lambda_gamma', 'lambda_delta', 'lambda_block']
N_PARAMS = 4


# ── Chromosome helpers ────────────────────────────────────────────────────────

def _random_chromosome(rng: random.Random) -> List[float]:
    return [rng.uniform(PARAM_MIN[i], PARAM_MAX[i]) for i in range(N_PARAMS)]


def _clamp(chromosome: List[float]) -> List[float]:
    return [max(PARAM_MIN[i], min(PARAM_MAX[i], chromosome[i]))
            for i in range(N_PARAMS)]


# ── Fitness evaluation ────────────────────────────────────────────────────────

def _evaluate(chromosome: List[float],
              scenario: List[Dict],
              alpha: float, beta: float,
              gamma: float, delta: float,
              sim_seed: int) -> Tuple[float, Dict]:
    """
    Apply chromosome parameters to simulator, run full simulation, return Z.
    """
    random.seed(sim_seed)
    sim = NavalFinalOptimizer(scenario, mode='GA', record_log=False)

    # Operator weights
    sim.alpha = alpha
    sim.beta  = beta
    sim.gamma = gamma
    sim.delta = delta

    # GA-optimised parameters
    sim.lambda_beta  = chromosome[0]
    sim.lambda_gamma = chromosome[1]
    sim.lambda_delta = chromosome[2]
    sim.lambda_block = chromosome[3]

    metrics = sim.run(max_h=HORIZON_H)

    s = metrics['shifting']
    f = metrics['fatigue']
    d = metrics['delay']
    e = metrics.get('emissions', 0.0)

    remaining = 1.0 - delta
    z = (remaining * 0.25 * (s / S_REF) +
         remaining * 0.25 * (f / F_REF) +
         remaining * 0.50 * ((d / 2) / D_REF) +  # d is in ticks, D_REF is in hours
         delta * (e / E_REF))

    sim.lambda_beta = chromosome[0]  # sets lambda to chromosome value

    return z, {'shifting': s, 'fatigue': f, 'delay': d, 'emissions': e}


# ── GA operators ──────────────────────────────────────────────────────────────

def _tournament_select(population: List, fitnesses: List[float],
                       k: int, rng: random.Random) -> List[float]:
    candidates = rng.sample(range(len(population)), k)
    best = min(candidates, key=lambda i: fitnesses[i])
    return population[best][:]


def _arithmetic_crossover(p1: List[float], p2: List[float],
                          rng: random.Random) -> Tuple[List[float], List[float]]:
    """Blend crossover — offspring are weighted blends of parents."""
    alpha = rng.random()
    c1 = [alpha * p1[i] + (1 - alpha) * p2[i] for i in range(N_PARAMS)]
    c2 = [(1 - alpha) * p1[i] + alpha * p2[i] for i in range(N_PARAMS)]
    return _clamp(c1), _clamp(c2)


def _gaussian_mutate(chromosome: List[float],
                     rng: random.Random) -> List[float]:
    """Add Gaussian noise to one randomly selected parameter."""
    chrom = chromosome[:]
    idx = rng.randint(0, N_PARAMS - 1)
    chrom[idx] += rng.gauss(0, MUTATION_STD)
    return _clamp(chrom)


# ── Main GA class ─────────────────────────────────────────────────────────────

class NavalGA:
    """
    Offline Genetic Algorithm that optimises the four fitness function
    multipliers of the greedy naval berth allocation dispatcher.

    Parameters
    ----------
    scenario : list of vessel dicts (from generate_scenario)
    alpha    : shifting weight
    beta     : fatigue weight
    gamma    : delay weight
    delta    : emission weight
    """

    def __init__(self, scenario: List[Dict],
                 alpha: float = 0.25, beta: float = 0.25,
                 gamma: float = 0.50, delta: float = 0.0):
        self.scenario = scenario
        self.alpha    = alpha
        self.beta     = beta
        self.gamma    = gamma
        self.delta    = delta

    def run(self,
            seed: int = 42,
            pop_size: int = POP_SIZE,
            n_generations: int = N_GENERATIONS,
            callback: Optional[Callable] = None,
            verbose: bool = True,
            ) -> Tuple[List[float], float, Dict]:
        """
        Run the GA. Returns (best_chromosome, best_z, stats).

        best_chromosome is [lambda_beta, lambda_gamma, lambda_delta, lambda_block]
        Apply these to the simulator before digital twin playback.
        """
        rng = random.Random(seed)
        t0  = time.time()

        if verbose:
            print(f"[NavalGA] pop={pop_size} gens={n_generations} "
                  f"seed={seed} δ={self.delta:.2f}")

        # ── Initialise population ─────────────────────────────────────────────
        # Always include default parameters as one chromosome
        population = [PARAM_DEFAULT[:]]
        while len(population) < pop_size:
            population.append(_random_chromosome(rng))

        # ── Evaluate initial population ───────────────────────────────────────
        if verbose:
            print(f"  Evaluating initial population ({pop_size} chromosomes)...")

        fitnesses = []
        for chrom in population:
            z, _ = _evaluate(chrom, self.scenario,
                             self.alpha, self.beta,
                             self.gamma, self.delta, seed)
            fitnesses.append(z)

        best_idx     = min(range(len(fitnesses)), key=lambda i: fitnesses[i])
        best_chrom   = population[best_idx][:]
        best_z       = fitnesses[best_idx]
        best_metrics = {}
        z_history    = [best_z]
        stagnant     = 0

        if verbose:
            mean_z = sum(fitnesses) / len(fitnesses)
            print(f"  Gen 0 | best Z={best_z:.4f} mean Z={mean_z:.4f}")
            print(f"  Default Z={fitnesses[0]:.4f} "
                  f"({'improved' if best_z < fitnesses[0] else 'default is best'})")

        # ── Evolution loop ────────────────────────────────────────────────────
        for gen in range(1, n_generations + 1):

            # Elitism — carry over best unchanged
            sorted_idx  = sorted(range(len(fitnesses)), key=lambda i: fitnesses[i])
            new_pop     = [population[i][:] for i in sorted_idx[:ELITE_N]]
            new_fitness = [fitnesses[i] for i in sorted_idx[:ELITE_N]]

            # Crossover + mutation
            while len(new_pop) < pop_size:
                p1 = _tournament_select(population, fitnesses, TOURNAMENT_K, rng)
                p2 = _tournament_select(population, fitnesses, TOURNAMENT_K, rng)

                if rng.random() < CROSSOVER_P:
                    c1, c2 = _arithmetic_crossover(p1, p2, rng)
                else:
                    c1, c2 = p1[:], p2[:]

                if rng.random() < MUTATION_P:
                    c1 = _gaussian_mutate(c1, rng)
                if rng.random() < MUTATION_P:
                    c2 = _gaussian_mutate(c2, rng)

                for child in [c1, c2]:
                    if len(new_pop) < pop_size:
                        z, metrics = _evaluate(
                            child, self.scenario,
                            self.alpha, self.beta,
                            self.gamma, self.delta, seed)
                        new_pop.append(child)
                        new_fitness.append(z)
                        if z < best_z:
                            best_z       = z
                            best_chrom   = child[:]
                            best_metrics = metrics
                            if verbose:
                                print(f"  *** Gen {gen} new best Z={best_z:.4f} "
                                      f"λβ={child[0]:.2f} λγ={child[1]:.2f} "
                                      f"λδ={child[2]:.2f} λb={child[3]:.2f}")

            population = new_pop
            fitnesses  = new_fitness
            z_history.append(best_z)

            # Convergence check
            if gen >= CONVERGE_GENS:
                improvement = z_history[-CONVERGE_GENS] - best_z
                if improvement < CONVERGE_TOL:
                    stagnant += 1
                    if stagnant >= CONVERGE_GENS:
                        if verbose:
                            print(f"  Early stop at gen {gen}")
                        break
                else:
                    stagnant = 0

            if verbose and gen % 10 == 0:
                mean_z = sum(new_fitness) / len(new_fitness)
                print(f"  Gen {gen:3d} | best Z={best_z:.4f} "
                      f"mean Z={mean_z:.4f} | {time.time()-t0:.1f}s")

            if callback:
                callback(gen, best_z, gen / n_generations)

        elapsed = round(time.time() - t0, 2)

        # Final evaluation for complete metrics
        _, best_metrics = _evaluate(
            best_chrom, self.scenario,
            self.alpha, self.beta,
            self.gamma, self.delta, seed)

        default_z = z_history[0]
        improvement_pct = (default_z - best_z) / default_z * 100

        if verbose:
            print(f"\n[NavalGA] Done in {elapsed}s | {len(z_history)-1} generations")
            print(f"  Default Z : {default_z:.4f}")
            print(f"  Best Z    : {best_z:.4f} ({improvement_pct:+.1f}%)")
            print(f"  Best params: λβ={best_chrom[0]:.3f} λγ={best_chrom[1]:.3f} "
                  f"λδ={best_chrom[2]:.3f} λb={best_chrom[3]:.3f}")
            m = best_metrics
            print(f"  Shifting:  {m.get('shifting','?')}")
            print(f"  Fatigue:   {m.get('fatigue','?'):.1f}")
            print(f"  Delay:     {m.get('delay','?'):.1f}h")
            print(f"  Emissions: {m.get('emissions',0)/1000:.1f}t CO2")

        return best_chrom, best_z, {
            'generations':      len(z_history) - 1,
            'time_s':           elapsed,
            'z_history':        z_history,
            'best_z':           best_z,
            'default_z':        default_z,
            'improvement_pct':  improvement_pct,
            'final_metrics':    best_metrics,
            'best_params': {
                'lambda_beta':  best_chrom[0],
                'lambda_gamma': best_chrom[1],
                'lambda_delta': best_chrom[2],
                'lambda_block': best_chrom[3],
            }
        }


def apply_ga_params(sim: NavalFinalOptimizer, chromosome: List[float]):
    """
    Apply GA-optimised parameters to a simulator instance.
    Call this before digital twin playback begins.
    """
    sim.lambda_beta  = chromosome[0]
    sim.lambda_gamma = chromosome[1]
    sim.lambda_delta = chromosome[2]
    sim.lambda_block = chromosome[3]


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    from Naval_sim_em_heuristics import generate_scenario

    print("Generating scenario (seed=42)...")
    random.seed(42)
    scen = generate_scenario(max_h=HORIZON_H)
    print(f"  {len(scen)} vessel arrivals\n")

    delta     = 0.0
    remaining = 1.0 - delta
    ga = NavalGA(scen,
                 alpha = remaining * 0.25,
                 beta  = remaining * 0.25,
                 gamma = remaining * 0.50,
                 delta = delta)

    best_chrom, best_z, stats = ga.run(seed=42, verbose=True)

    print(f"\nImprovement: {stats['default_z']:.4f} → {best_z:.4f} "
          f"({stats['improvement_pct']:+.1f}%)")