# test_step_api.py
from Naval_sim_core import generate_scenario, NavalFinalOptimizer

print("=== Testing refactored NavalFinalOptimizer ===")

# test basic step API
scen = generate_scenario()
sim = NavalFinalOptimizer(scen, mode='GA')
sim.reset()
print(f"t=0: ships={len([s for s in sim.scenario])}")
for i in range(10):
    sim.step()
    print(f"t={sim.t}: weather={sim.weather_level}")

print("\n=== Testing original run() ===")
sim.reset()
result = sim.run(max_h=50)  # short run for test
print("Original run() still works:", result)

print("\n=== SUCCESS: Both step() and run() work ===")