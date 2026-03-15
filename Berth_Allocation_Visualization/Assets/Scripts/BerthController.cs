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
 *   - RescheduleResult on weather    → Console shows before/after diff
 */
 
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
 
// ── Reschedule result data classes ───────────────────────────────────────────
 
[System.Serializable]
public class AffectedVessel
{
    public string id;
    public string type;
    public string action;
    public string pier;
    public int    layer;
    public float  from;
    public float  to;
}
 
[System.Serializable]
public class RescheduleMetrics
{
    public int   shifting;
    public float fatigue;
    public float delay;
    public float combined;
}
 
[System.Serializable]
public class RescheduleResult
{
    public bool              ok;
    public string            message;
    public int               weather_level;
    public float             duration_h;
    public AffectedVessel[]  affected;
    public RescheduleMetrics metrics_before;
    public RescheduleMetrics metrics_after;
    public SimSnapshot       state;
}
 
// ── BerthController ───────────────────────────────────────────────────────────
 
public class BerthController : AllocatorAPIClient
{
    [Header("Scene References")]
    public PortVisualizer portVisualizer;
 
    [Header("Playback")]
    [Tooltip("Seconds between ticks. Controlled at runtime by SimulationClock.")]
    public float playbackInterval = 0.5f;
 
    public event System.Action<RescheduleResult> OnReschedule;
 
    private bool _autoSteppingField = false;
    public bool IsRunning => _autoSteppingField;
 
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
 
    // ── Night / lunch (mirrors Naval_sim_core) ────────────────────────────────
 
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
 
        yield return StartCoroutine(HealthCheck(health =>
        {
            if (health == null)
                Debug.LogError("[BerthController] Server unreachable.");
            else
                Debug.Log($"[BerthController] Connected v{health.version} | MILP: {health.milp}");
        }));
 
        InitResponse initResp = null;
        yield return StartCoroutine(InitScenario(
            horizonH: HorizonH,
            seed:     Seed,
            mode:     Mode,
            onDone:   r => initResp = r
        ));
        LogSessionReady(initResp);
        StartAutoStep(playbackInterval);
    }
 
    private IEnumerator DeleteAllSessions()
    {
        using var req = UnityWebRequest.Delete(ServerUrl + "/sessions/all");
        req.timeout = 5;
        yield return req.SendWebRequest();
    }
 
    private void LogSessionReady(InitResponse resp)
    {
        if (resp == null) return;
        var c = resp.vessel_counts;
        string counts = c != null
            ? $"K:{c.K}  F:{c.F}  L:{c.L}  P:{c.P}"
            : "counts unavailable";
        Debug.Log($"[BerthController] Session {resp.session_id.Substring(0, 8)}... | " +
                  $"Total: {resp.vessels} vessels  ({counts}) | " +
                  $"Horizon: {resp.horizon_h}h | Seed: {resp.seed} | Mode: {resp.mode}");
    }
 
    // =========================================================================
    // Visualization
    // =========================================================================
 
    private StateMessage ToStateMessage(SimSnapshot snap)
    {
        var ships = new ShipState[snap.vessels.Length];
        for (int i = 0; i < snap.vessels.Length; i++)
        {
            var v    = snap.vessels[i];
            string pier  = "";
            int    layer = -1;
            foreach (var b in snap.berths)
            {
                if (b.occupied && b.vessel_id == v.id)
                {
                    pier  = b.pier;
                    layer = b.layer;
                    break;
                }
            }
            ships[i] = new ShipState
            {
                id          = v.id,
                type        = v.type,
                status      = v.status,
                pier        = pier,
                layer       = layer,
                arr_time    = v.arr_h,
                dep_planned = v.arr_h + v.stay_h,
                dep_actual  = 0,
            };
        }
 
        var tugs = new TugState[6];
        for (int t = 0; t < 6; t++)
            tugs[t] = new TugState
            {
                id        = "Tug" + (t + 1),
                status    = snap.weather_level == 3 ? "Unavailable" : "Ready",
                free_time = 0,
            };
 
        return new StateMessage
        {
            time     = (int)snap.time_h,
            weather  = snap.weather_level,
            is_night = IsNight(snap.tick),
            is_lunch = IsLunch(snap.tick),
            ships    = ships,
            tugs     = tugs,
            metrics  = new Metrics
            {
                shifting = snap.metrics.shifting,
                fatigue  = snap.metrics.fatigue,
                delay    = snap.metrics.delay,
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
    // Weather event (Unity → Python two-way)
    // =========================================================================
 
    public void OnWeatherSliderChanged(float value)
    {
        StartCoroutine(SendWeatherEvent(Mathf.RoundToInt(value), 8f));
    }
 
    private IEnumerator SendWeatherEvent(int level, float durationH)
    {
        if (string.IsNullOrEmpty(SessionId)) yield break;
 
        bool wasRunning = IsRunning;
        StopAutoStep();
 
        Debug.Log("[BerthController] Weather -> " + WeatherName(level) + " — rescheduling...");
 
        string body = "{\"session_id\":\"" + SessionId + "\"," +
                      "\"level\":" + level + "," +
                      "\"duration_h\":" + durationH + "}";
 
        var result = new HttpResult();
        yield return PostRequest("/set_weather_event", body, result);
 
        if (!result.Ok)
        {
            Debug.LogError("[BerthController] Weather event failed: " + result.Body);
            if (wasRunning) StartAutoStep(playbackInterval);
            yield break;
        }
 
        var reschedule = JsonUtility.FromJson<RescheduleResult>(result.Body);
 
        if (reschedule.state != null)
            UpdateVisualization(reschedule.state);
 
        Debug.Log("[BerthController] " + reschedule.message);
        Debug.Log("  Delay: " + reschedule.metrics_before.delay.ToString("F1") +
                  "h -> " + reschedule.metrics_after.delay.ToString("F1") + "h");
        Debug.Log("  Shifting: " + reschedule.metrics_before.shifting +
                  " -> " + reschedule.metrics_after.shifting);
 
        if (reschedule.affected != null && reschedule.affected.Length > 0)
            foreach (var v in reschedule.affected)
                Debug.Log("    " + v.id + " (" + v.type + "): " + v.action +
                          "  " + v.from.ToString("F0") + "h -> " + v.to.ToString("F0") + "h");
 
        OnReschedule?.Invoke(reschedule);
        if (wasRunning) StartAutoStep(playbackInterval);
    }
 
    private static string WeatherName(int level)
    {
        switch (level)
        {
            case 0: return "Clear";
            case 1: return "Light";
            case 2: return "Moderate";
            case 3: return "Storm";
            default: return "Level " + level;
        }
    }
 
    // =========================================================================
    // Scenario loader (called by OperatorPanel)
    // =========================================================================
 
    public void LoadScenario(int seed, int horizonH, string mode = "GA",
                              int cK = -1, int cF = -1, int cL = -1, int cP = -1)
    {
        StopAutoStep();
        StartCoroutine(LoadScenarioCoroutine(seed, horizonH, mode, cK, cF, cL, cP));
    }
 
    private IEnumerator LoadScenarioCoroutine(int seed, int horizonH, string mode,
                                               int cK, int cF, int cL, int cP)
    {
        string countsJson = BuildVesselCountsJson(cK, cF, cL, cP);
        InitResponse resp = null;
        yield return StartCoroutine(InitScenario(
            horizonH:        horizonH,
            seed:            seed,
            mode:            mode,
            forceRecalc:     true,
            onDone:          r => resp = r,
            vesselCountsJson: countsJson
        ));
        LogSessionReady(resp);
        StartAutoStep(playbackInterval);
    }
 
    private static string BuildVesselCountsJson(int cK, int cF, int cL, int cP)
    {
        if (cK < 0 && cF < 0 && cL < 0 && cP < 0)
            return "null";
 
        var sb = new StringBuilder("{");
        bool first = true;
 
        if (cK >= 0) { sb.Append("\"K\":").Append(cK); first = false; }
        if (cF >= 0) { if (!first) sb.Append(","); sb.Append("\"F\":").Append(cF); first = false; }
        if (cL >= 0) { if (!first) sb.Append(","); sb.Append("\"L\":").Append(cL); first = false; }
        if (cP >= 0) { if (!first) sb.Append(","); sb.Append("\"P\":").Append(cP); }
 
        sb.Append("}");
        return sb.ToString();
    }
 
    // =========================================================================
    // Playback controls
    // =========================================================================
 
    public void OnPlayButtonClick()  => StartAutoStep(playbackInterval);
    public void OnPauseButtonClick() => StopAutoStep();
    public void OnStepButtonClick()  => StartCoroutine(StepForward(1));
 
    public void OnResetButtonClick()
    {
        StopAutoStep();
        StartCoroutine(ResetAndPlay());
    }
 
    private IEnumerator ResetAndPlay()
    {
        yield return StartCoroutine(InitScenario(
            horizonH:    HorizonH,
            seed:        Seed,
            mode:        Mode,
            forceRecalc: true
        ));
        Debug.Log("[BerthController] Reset complete — restarting.");
        StartAutoStep(playbackInterval);
    }
 
    // =========================================================================
    // Finish handler
    // =========================================================================
 
    void OnEnable()  => OnSimFinished += HandleSimFinished;
    void OnDisable() => OnSimFinished -= HandleSimFinished;
 
    private void HandleSimFinished(SimSnapshot snap)
    {
        StopAutoStep();
        Debug.Log("[BerthController] Simulation complete  t=" + snap.time_h + "h | " +
                  "Shifting=" + snap.metrics.shifting + " | " +
                  "Fatigue=" + snap.metrics.fatigue.ToString("F1") + " | " +
                  "Delay=" + snap.metrics.delay.ToString("F1") + "h");
    }
 
    // =========================================================================
    // HTTP helper
    // =========================================================================
 
    private IEnumerator PostRequest(string endpoint, string jsonBody,
                                     HttpResult result, int timeoutSeconds = 30)
    {
        var bytes = Encoding.UTF8.GetBytes(jsonBody);
        using var req = new UnityWebRequest(ServerUrl + endpoint, "POST")
        {
            uploadHandler   = new UploadHandlerRaw(bytes),
            downloadHandler = new DownloadHandlerBuffer(),
            timeout         = timeoutSeconds,
        };
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();
 
        result.Ok   = req.result == UnityWebRequest.Result.Success;
        result.Body = result.Ok ? req.downloadHandler.text : req.error;
 
        if (!result.Ok)
            Debug.LogError("[BerthController] POST " + endpoint + ": " + req.error);
    }
}