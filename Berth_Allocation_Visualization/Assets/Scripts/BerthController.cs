/*
 * BerthController.cs
 * ==================
 * Subclasses AllocatorAPIClient and bridges the server's SimSnapshot
 * to your existing PortVisualizer / StateMessage format.
 *
 * Setup:
 *  1. On your SimManager GameObject:
 *       - Remove AllocatorAPIClient component (if added)
 *       - Add BerthController component
 *  2. Drag your PortVisualizer GameObject into the portVisualizer field
 *  3. Add UI buttons and wire them to the public methods below
 */

using UnityEngine;
using Naval;

// ── BerthController ───────────────────────────────────────────────────────────

public class BerthController : AllocatorAPIClient
{
    [Header("Scene References")]
    public PortVisualizer portVisualizer;

    [Header("Playback")]
    [Tooltip("Seconds between ticks during auto-play (0.1 = 10 ticks/sec)")]
    public float playbackInterval = 0.1f;

    // ── Night / lunch helpers (mirror Naval_sim_core logic) ──────────────────
    // Night: tick mod 48 >= 44 OR <= 14  (i.e. 22:00-07:00)
    // Lunch: tick mod 48 == 25 or 26     (i.e. 12:30-13:00)
    private static bool IsNight(int tick)
    {
        int mod = tick % 48;
        return mod >= 44 || mod <= 14;
    }

    private static bool IsLunch(int tick)
    {
        int mod = tick % 48;
        return mod == 25 || mod == 26;
    }

    // ── Adapter: SimSnapshot → StateMessage ──────────────────────────────────

    private StateMessage ToStateMessage(SimSnapshot snap)
    {
        // Ships — merge vessel list with current berth occupancy
        var ships = new ShipState[snap.vessels.Length];
        for (int i = 0; i < snap.vessels.Length; i++)
        {
            var v = snap.vessels[i];

            // Find which berth this vessel is at (if any)
            string pier = null;
            int layer = -1;
            foreach (var b in snap.berths)
            {
                if (b.occupied && b.vessel_id == v.id)
                {
                    pier = b.pier;
                    layer = b.layer;
                    break;
                }
            }

            ships[i] = new ShipState
            {
                id = v.id,
                type = v.type,
                status = v.status,
                pier = pier ?? "",
                layer = layer,
                arr_time = v.arr_h,
                dep_planned = v.arr_h + v.stay_h,
                dep_actual = 0,
            };
        }

        // Tugs — server doesn't expose individual tugs, synthesise from weather
        // (real tug states would need a server-side addition)
        var tugs = new TugState[6];
        for (int t = 0; t < 6; t++)
        {
            tugs[t] = new TugState
            {
                id = $"Tug{t + 1}",
                status = snap.weather_level == 3 ? "Unavailable" : "Ready",
                free_time = 0,
            };
        }

        return new StateMessage
        {
            time = (int)snap.time_h,
            weather = snap.weather_level,
            is_night = IsNight(snap.tick),
            is_lunch = IsLunch(snap.tick),
            ships = ships,
            tugs = tugs,
            metrics = new Metrics
            {
                shifting = snap.metrics.shifting,
                fatigue = snap.metrics.fatigue,
                delay = snap.metrics.delay,
            },
        };
    }

    // ── Override UpdateVisualization ─────────────────────────────────────────

    protected override void UpdateVisualization(SimSnapshot snap)
    {
        if (portVisualizer == null)
        {
            Debug.LogWarning("[BerthController] portVisualizer not assigned.");
            return;
        }
        portVisualizer.ApplyState(ToStateMessage(snap));
    }

    // ── UI button handlers ───────────────────────────────────────────────────

    /// <summary>Wire to a Step button.</summary>
    public void OnStepButtonClick()
    {
        StartCoroutine(StepForward(1));
    }

    /// <summary>Wire to a Play button.</summary>
    public void OnPlayButtonClick()
    {
        StartAutoStep(playbackInterval);
    }

    /// <summary>Wire to a Pause button.</summary>
    public void OnPauseButtonClick()
    {
        StopAutoStep();
    }

    /// <summary>Wire to a weather slider (0-3).</summary>
    public void OnWeatherSliderChanged(float value)
    {
        OnEnvironmentChange(weatherLevel: Mathf.RoundToInt(value), durationH: 4f);
    }

    /// <summary>Wire to a Reset button.</summary>
    public void OnResetButtonClick()
    {
        StartCoroutine(InitScenario(
            horizonH: HorizonH,
            seed: Seed,
            mode: Mode,
            forceRecalc: true
        ));
    }

    /// <summary>
    /// Load a specific scenario by seed.
    /// Call from code: berthController.LoadScenario(seed: 42, mode: "GA");
    /// </summary>
    public void LoadScenario(int seed, string mode = "GA")
    {
        StartCoroutine(InitScenario(
            horizonH: HorizonH,
            seed: seed,
            mode: mode,
            forceRecalc: true
        ));
    }

    // ── Finish handler ───────────────────────────────────────────────────────

    void OnEnable()
    {
        OnSimFinished += HandleSimFinished;
    }

    void OnDisable()
    {
        OnSimFinished -= HandleSimFinished;
    }

    private void HandleSimFinished(SimSnapshot snap)
    {
        Debug.Log($"[BerthController] Simulation complete at t={snap.time_h}h | " +
                  $"Shifting={snap.metrics.shifting} | " +
                  $"Fatigue={snap.metrics.fatigue:F1} | " +
                  $"Delay={snap.metrics.delay:F1}h");
        StopAutoStep();
    }
}