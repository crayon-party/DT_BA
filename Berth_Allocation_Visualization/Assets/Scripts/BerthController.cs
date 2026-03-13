/*
 * BerthController.cs
 * ==================
 * Two-way digital twin controller.
 *
 * Unity → Python:
 *   - Weather change  → POST /set_weather_event  (GA reschedules, returns diff)
 *   - New scenario    → POST /init_scenario       (vessel count, horizon, seed)
 *   - Step / Play / Pause / Reset
 *
 * Python → Unity:
 *   - SimSnapshot after every step   → PortVisualizer renders live state
 *   - RescheduleResult on weather    → Console + ReschedulePanel shows before/after
 */

using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using Naval;

// ── Reschedule result data classes ───────────────────────────────────────────

[System.Serializable]
public class AffectedVessel
{
    public string id;
    public string type;
    public string action;   // "arrival_delayed" | "departure_delayed"
    public string pier;
    public int layer;
    public float from;     // old time in hours
    public float to;       // new time in hours
}

[System.Serializable]
public class RescheduleMetrics
{
    public int shifting;
    public float fatigue;
    public float delay;
    public float combined;
}

[System.Serializable]
public class RescheduleResult
{
    public bool ok;
    public string message;
    public int weather_level;
    public float duration_h;
    public AffectedVessel[] affected;
    public RescheduleMetrics metrics_before;
    public RescheduleMetrics metrics_after;
    public SimSnapshot state;
}

// ── BerthController ───────────────────────────────────────────────────────────

public class BerthController : AllocatorAPIClient
{
    [Header("Scene References")]
    public PortVisualizer portVisualizer;

    [Header("Playback")]
    [Tooltip("Seconds between ticks. Controlled at runtime by SimulationClock.")]
    public float playbackInterval = 0.5f;

    // ── Events ────────────────────────────────────────────────────────────────
    public event System.Action<RescheduleResult> OnReschedule;

    // ── Night / lunch helpers (mirror Naval_sim_core) ─────────────────────────
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

    // =========================================================================
    // Startup
    // =========================================================================

    protected override void Start()
    {
        StartCoroutine(StartupAndPlay());
    }

    private IEnumerator StartupAndPlay()
    {
        yield return StartCoroutine(DeleteAllSessions());
        yield return StartCoroutine(StartupSequence());
        Debug.Log("[BerthController] Session ready — starting auto-step.");
        StartAutoStep(playbackInterval);
    }

    private IEnumerator DeleteAllSessions()
    {
        using var req = UnityWebRequest.Delete(ServerUrl + "/sessions/all");
        req.timeout = 5;
        yield return req.SendWebRequest();
    }

    // =========================================================================
    // Visualization adapter: SimSnapshot → StateMessage → PortVisualizer
    // =========================================================================

    private StateMessage ToStateMessage(SimSnapshot snap)
    {
        var ships = new ShipState[snap.vessels.Length];
        for (int i = 0; i < snap.vessels.Length; i++)
        {
            var v = snap.vessels[i];
            string pier = "";
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
                pier = pier,
                layer = layer,
                arr_time = v.arr_h,
                dep_planned = v.arr_h + v.stay_h,
                dep_actual = 0,
            };
        }

        var tugs = new TugState[6];
        for (int t = 0; t < 6; t++)
            tugs[t] = new TugState
            {
                id = $"Tug{t + 1}",
                status = snap.weather_level == 3 ? "Unavailable" : "Ready",
                free_time = 0,
            };

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

    protected override void UpdateVisualization(SimSnapshot snap)
    {
        if (portVisualizer == null)
        {
            Debug.LogWarning("[BerthController] portVisualizer not assigned.");
            return;
        }
        portVisualizer.ApplyState(ToStateMessage(snap));
    }

    // =========================================================================
    // Unity → Python: Weather event (true two-way)
    // =========================================================================

    /// <summary>
    /// Wire to weather slider (Min=0, Max=3, Whole Numbers=ON).
    /// Sends weather to Python, GA reschedules, Unity receives and shows result.
    /// </summary>
    public void OnWeatherSliderChanged(float value)
    {
        int level = Mathf.RoundToInt(value);
        StartCoroutine(SendWeatherEvent(level, durationH: 8f));
    }

    private IEnumerator SendWeatherEvent(int level, float durationH)
    {
        if (string.IsNullOrEmpty(SessionId)) yield break;

        bool wasAutoStepping = IsAutoStepping;
        StopAutoStep();

        Debug.Log($"[BerthController] ⚡ Weather → {WeatherName(level)} — pausing, rescheduling...");

        string body = "{" +
            $"\"session_id\":\"{SessionId}\"," +
            $"\"level\":{level}," +
            $"\"duration_h\":{durationH}" +
            "}";

        var result = new HttpResult();
        yield return PostRequest("/set_weather_event", body, result);

        if (!result.Ok)
        {
            Debug.LogError($"[BerthController] Weather event failed: {result.Body}");
            if (wasAutoStepping) StartAutoStep(playbackInterval);
            yield break;
        }

        var reschedule = JsonUtility.FromJson<RescheduleResult>(result.Body);

        // Immediately update visualization with rescheduled state
        if (reschedule.state != null)
            UpdateVisualization(reschedule.state);

        // Log summary
        Debug.Log($"[BerthController] ✓ {reschedule.message}");
        Debug.Log($"  Delay:    {reschedule.metrics_before.delay:F1}h → {reschedule.metrics_after.delay:F1}h " +
                  $"(Δ {reschedule.metrics_after.delay - reschedule.metrics_before.delay:+0.1;-0.1}h)");
        Debug.Log($"  Shifting: {reschedule.metrics_before.shifting} → {reschedule.metrics_after.shifting}");

        if (reschedule.affected != null && reschedule.affected.Length > 0)
        {
            Debug.Log($"  Affected vessels ({reschedule.affected.Length}):");
            foreach (var v in reschedule.affected)
                Debug.Log($"    {v.id} ({v.type}): {v.action}  {v.from:F0}h → {v.to:F0}h");
        }
        else
        {
            Debug.Log("  No vessels rescheduled.");
        }

        OnReschedule?.Invoke(reschedule);

        // Resume
        if (wasAutoStepping) StartAutoStep(playbackInterval);
    }

    // Expose auto-stepping state for SendWeatherEvent
    private bool IsAutoStepping => _autoSteppingField;

    // Reflection-free way: track it ourselves
    private bool _autoSteppingField = false;

    public new void StartAutoStep(float intervalSec)
    {
        _autoSteppingField = true;
        base.StartAutoStep(intervalSec);
    }

    public new void StopAutoStep()
    {
        _autoSteppingField = false;
        base.StopAutoStep();
    }

    private static string WeatherName(int level) => level switch
    {
        0 => "Clear",
        1 => "Light",
        2 => "Moderate",
        3 => "Storm",
        _ => $"Level {level}"
    };

    // =========================================================================
    // Unity → Python: Scenario parameters
    // =========================================================================

    /// <summary>
    /// Load a new scenario with custom parameters.
    /// Called from ScenarioPanel UI.
    /// </summary>
    public void LoadScenario(int seed, int horizonH, string mode = "GA")
    {
        StopAutoStep();
        StartCoroutine(LoadScenarioCoroutine(seed, horizonH, mode));
    }

    private IEnumerator LoadScenarioCoroutine(int seed, int horizonH, string mode)
    {
        Debug.Log($"[BerthController] Loading: seed={seed}  horizon={horizonH}h  mode={mode}");
        yield return StartCoroutine(InitScenario(
            horizonH: horizonH,
            seed: seed,
            mode: mode,
            forceRecalc: true
        ));
        Debug.Log("[BerthController] New scenario ready — starting.");
        StartAutoStep(playbackInterval);
    }

    // =========================================================================
    // Playback controls
    // =========================================================================

    public void OnPlayButtonClick() => StartAutoStep(playbackInterval);
    public void OnPauseButtonClick() => StopAutoStep();
    public void OnStepButtonClick() => StartCoroutine(StepForward(1));

    public void OnResetButtonClick()
    {
        StopAutoStep();
        StartCoroutine(ResetAndPlay());
    }

    private IEnumerator ResetAndPlay()
    {
        yield return StartCoroutine(InitScenario(
            horizonH: HorizonH,
            seed: Seed,
            mode: Mode,
            forceRecalc: true
        ));
        Debug.Log("[BerthController] Reset complete — restarting.");
        StartAutoStep(playbackInterval);
    }

    // =========================================================================
    // Finish handler
    // =========================================================================

    void OnEnable() => OnSimFinished += HandleSimFinished;
    void OnDisable() => OnSimFinished -= HandleSimFinished;

    private void HandleSimFinished(SimSnapshot snap)
    {
        StopAutoStep();
        Debug.Log($"[BerthController] ✓ Simulation complete  t={snap.time_h}h | " +
                  $"Shifting={snap.metrics.shifting} | " +
                  $"Fatigue={snap.metrics.fatigue:F1} | " +
                  $"Delay={snap.metrics.delay:F1}h");
    }

    // =========================================================================
    // HTTP helper for endpoints not in base class
    // =========================================================================

    private IEnumerator PostRequest(string endpoint, string jsonBody,
                                     HttpResult result, int timeoutSeconds = 30)
    {
        var bytes = Encoding.UTF8.GetBytes(jsonBody);
        using var req = new UnityWebRequest(ServerUrl + endpoint, "POST")
        {
            uploadHandler = new UploadHandlerRaw(bytes),
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = timeoutSeconds,
        };
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();

        result.Ok = req.result == UnityWebRequest.Result.Success;
        result.Body = result.Ok ? req.downloadHandler.text : req.error;

        if (!result.Ok)
            Debug.LogError($"[BerthController] POST {endpoint}: {req.error}");
    }
}