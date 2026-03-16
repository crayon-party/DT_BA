/*
 * NavalApiClient.cs
 * =================
 * Unity HTTP client for the Naval Berth Digital Twin FastAPI server.
 * Plain UnityWebRequest only — no WebSocket, no extra packages required.
 *
 * CS1621-safe: no yield inside lambdas or anonymous methods.
 * All coroutines yield the request directly and read results afterward.
 *
 * Usage
 * -----
 *  1. Attach to a persistent GameObject (e.g. "SimManager").
 *  2. Set ServerUrl in the Inspector (default: http://localhost:8000).
 *
 *     // Scene start — auto-init runs in Start()
 *
 *     // Tick-by-tick
 *     StartCoroutine(client.StepForward(1));
 *
 *     // Continuous playback
 *     client.StartAutoStep(intervalSec: 0.1f);
 *     client.StopAutoStep();
 *
 *     // Weather slider changed
 *     client.OnEnvironmentChange(weatherLevel: 2, durationH: 6f);
 *
 *     // Research comparison
 *     StartCoroutine(client.Compare(resp => ShowResultsPanel(resp)));
 *
 * Dependencies: Unity 2021+  (no extra packages)
 */

using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

// =========================================================================
// Data models — mirror snapshot_to_dict() on the Python side
// =========================================================================

[Serializable]
public class HealthResponse
{
    public string status;
    public string version;
    public bool milp;
    public int sessions;
}

[Serializable]
public class BerthSlot
{
    public string pier;
    public int layer;
    public string vessel_id;
    public string vessel_type;
    public bool occupied;
}

[Serializable]
public class VesselStatus
{
    public string id;
    public string type;
    public string status;       // "queued" | "berthed" | "departed"
    public string pier;
    public int layer;
    public int arr_tick;
    public int arr_h;
    public int stay_h;
}

/// <summary>
/// Full simulation snapshot — returned by every REST call.
/// This is the input to UpdateVisualization().
/// </summary>
[Serializable]
public class SimSnapshot
{
    public string session_id;
    public int tick;
    public float time_h;
    public int weather_level;
    public int weather_rem;
    public bool finished;
    public Metrics metrics;
    public BerthSlot[] berths;
    public VesselStatus[] vessels;
}

[Serializable]
public class VesselCounts
{
    public int K;   // Destroyer
    public int F;   // Frigate
    public int L;   // Landing
    public int P;   // Patrol
}

[Serializable]
public class InitResponse
{
    public string session_id;
    public bool reused;
    public int vessels;
    public VesselCounts vessel_counts;
    public int horizon_h;
    public int seed;
    public string mode;
    public SimSnapshot state;
}

[Serializable]
public class StepResponse
{
    public bool finished;
    public SimSnapshot state;
}

[Serializable]
public class SolverResult
{
    public int shifting;
    public float fatigue;
    public float delay;
    public float combined;
    public float gap_vs_milp;
    public float improvement_vs_fcfs;
    public string status;
}

[Serializable]
public class CompareResults
{
    public SolverResult MILP;
    public SolverResult GA;
    public SolverResult FCFS;
}

[Serializable]
public class CompareResponse
{
    public int horizon_h;
    public int seed;
    public int n_vessels;
    public float milp_solve_s;
    public CompareResults results;
}

// =========================================================================
// Internal helper — carries HTTP result out of the yield
// =========================================================================

internal class HttpResult
{
    public bool Ok;
    public string Body;
}

// =========================================================================
// AllocatorAPIClient
// =========================================================================

public class AllocatorAPIClient : MonoBehaviour
{
    // ── Inspector ─────────────────────────────────────────────────────────

    [Header("Server")]
    public string ServerUrl = "http://localhost:8000";

    [Header("Default Scenario")]
    public int HorizonH = 168;
    public int Seed = 42;
    public string Mode = "GA";

    // ── Runtime state ─────────────────────────────────────────────────────

    public string SessionId { get; private set; }
    public SimSnapshot CurrentState { get; private set; }

    // ── Events ────────────────────────────────────────────────────────────

    /// <summary>Fired after every step. Wire to UpdateVisualization().</summary>
    public event Action<SimSnapshot> OnStateUpdate;

    /// <summary>Fired when the simulation finishes.</summary>
    public event Action<SimSnapshot> OnSimFinished;

    /// <summary>Fired on any HTTP error.</summary>
    public event Action<string> OnApiError;

    // =====================================================================
    // Scene lifecycle
    // =====================================================================

    protected virtual void Start()
    {
        StartCoroutine(StartupSequence());
    }

    protected IEnumerator StartupSequence()
    {
        // 1. Health check
        var health = new HttpResult();
        yield return Get("/health", health);

        if (!health.Ok)
        {
            Debug.LogError("[NavalApi] Server unreachable. Is naval_api_server.py running?");
            yield break;
        }

        var h = JsonUtility.FromJson<HealthResponse>(health.Body);
        Debug.Log($"[NavalApi] Connected v{h.version} | MILP: {h.milp} | Sessions: {h.sessions}");

        // 2. Init default scenario
        yield return StartCoroutine(InitScenario(HorizonH, Seed, Mode));
    }

    void OnDestroy()
    {
        if (!string.IsNullOrEmpty(SessionId))
            StartCoroutine(DeleteSession(SessionId));
    }

    // =====================================================================
    // Core simulation loop
    // =====================================================================

    /// <summary>
    /// Create or re-initialise a session.
    /// Leave customVessels null to auto-generate from seed on the server.
    /// </summary>
    public IEnumerator InitScenario(
        int horizonH,
        int seed,
        string mode,
        Action<InitResponse> onDone = null,
        string customVessels = null,
        bool forceRecalc = false,
        string vesselCountsJson = null)
    {
        string vessels = customVessels ?? "null";
        string vesselCounts = vesselCountsJson ?? "null";
        string body = "{" +
            "\"horizon_h\":" + horizonH + "," +
            "\"seed\":" + seed + "," +
            "\"mode\":\"" + mode + "\"," +
            "\"current_time\":0," +
            "\"force_recalc\":" + (forceRecalc ? "true" : "false") + "," +
            "\"vessels\":" + vessels + "," +
            "\"vessel_counts\":" + vesselCounts +
            "}";

        var result = new HttpResult();
        yield return Post("/init_scenario", body, result);

        if (!result.Ok)
        {
            onDone?.Invoke(null);
            yield break;
        }

        var resp = JsonUtility.FromJson<InitResponse>(result.Body);
        SessionId = resp.session_id;
        CurrentState = resp.state;
        OnStateUpdate?.Invoke(CurrentState);
        Debug.Log($"[NavalApi] Session ready: {resp.session_id} ({resp.vessels} vessels)");
        onDone?.Invoke(resp);
    }

    /// <summary>
    /// Advance the simulation by ticks (1 tick = 0.5 h).
    /// Automatically fires OnStateUpdate and OnSimFinished.
    /// </summary>
    public IEnumerator StepForward(int ticks = 1, Action<StepResponse> onDone = null)
    {
        if (string.IsNullOrEmpty(SessionId))
        {
            Debug.LogWarning("[NavalApi] No active session. Call InitScenario first.");
            onDone?.Invoke(null);
            yield break;
        }

        string body = $"{{\"session_id\":\"{SessionId}\",\"ticks\":{ticks}}}";

        var result = new HttpResult();
        yield return Post("/step_forward", body, result);

        if (!result.Ok)
        {
            onDone?.Invoke(null);
            yield break;
        }

        var resp = JsonUtility.FromJson<StepResponse>(result.Body);
        CurrentState = resp.state;
        UpdateVisualization(CurrentState);
        OnStateUpdate?.Invoke(CurrentState);

        if (resp.finished)
            OnSimFinished?.Invoke(CurrentState);

        onDone?.Invoke(resp);
    }

    /// <summary>
    /// Called when Unity environment changes (weather slider, etc.).
    /// Mirrors original OnEnvironmentChange().
    /// </summary>
    public void OnEnvironmentChange(int weatherLevel, float durationH = 4f)
    {
        if (string.IsNullOrEmpty(SessionId)) return;
        StartCoroutine(SetWeather(weatherLevel, durationH));
    }

    /// <summary>
    /// Override in a subclass or subscribe to OnStateUpdate.
    /// Spawn/move vessel GameObjects, update Gantt and metrics HUD here.
    /// </summary>
    protected virtual void UpdateVisualization(SimSnapshot snap)
    {
        if (snap == null) return;
        Debug.Log($"[NavalApi] t={snap.time_h:F1}h  " +
                  $"shift={snap.metrics.shifting}  " +
                  $"fat={snap.metrics.fatigue:F1}  " +
                  $"delay={snap.metrics.delay:F1}h  " +
                  $"weather={snap.weather_level}");
    }

    // =====================================================================
    // Simulation controls
    // =====================================================================

    /// <summary>Inject a weather event into the running session.</summary>
    public IEnumerator SetWeather(int level, float durationH = 4f,
                                   Action<bool> onDone = null)
    {
        string body = $"{{\"session_id\":\"{SessionId}\"," +
                      $"\"level\":{level},\"duration_h\":{durationH}}}";

        var result = new HttpResult();
        yield return Post("/set_weather", body, result);
        onDone?.Invoke(result.Ok);
    }

    /// <summary>Get a fresh snapshot without advancing the sim.</summary>
    public IEnumerator GetState(Action<SimSnapshot> onDone)
    {
        var result = new HttpResult();
        yield return Get($"/state/{SessionId}", result);

        if (!result.Ok) { onDone?.Invoke(null); yield break; }

        CurrentState = JsonUtility.FromJson<SimSnapshot>(result.Body);
        onDone?.Invoke(CurrentState);
    }

    // =====================================================================
    // Auto-step loop — continuous playback via polling
    // =====================================================================

    private bool _autoStepping = false;

    /// <summary>
    /// Step continuously, one tick every intervalSec real seconds.
    /// Fires OnStateUpdate and OnSimFinished as normal.
    /// </summary>
    public void StartAutoStep(float intervalSec = 0.1f)
    {
        if (_autoStepping) return;
        _autoStepping = true;
        StartCoroutine(AutoStepLoop(intervalSec));
    }

    public void StopAutoStep() => _autoStepping = false;

    private IEnumerator AutoStepLoop(float interval)
    {
        while (_autoStepping)
        {
            StepResponse resp = null;
            yield return StartCoroutine(StepForward(1, r => resp = r));

            if (resp == null || resp.finished)
            {
                _autoStepping = false;
                yield break;
            }

            yield return new WaitForSeconds(interval);
        }
    }

    // =====================================================================
    // Solvers
    // =====================================================================

    /// <summary>Run solver to completion. solver: "GA" | "FCFS" | "BOTH"</summary>
    public IEnumerator RunFull(string solver, Action<string> onDone)
    {
        string body = $"{{\"horizon_h\":{HorizonH},\"seed\":{Seed}," +
                      $"\"solver\":\"{solver}\"}}";

        var result = new HttpResult();
        yield return Post("/run_full", body, result);
        onDone?.Invoke(result.Ok ? result.Body : null);
    }

    /// <summary>Run MILP and get the optimal schedule (may take 5-30 s).</summary>
    public IEnumerator SolveMilp(int timeLimitS, Action<string> onDone)
    {
        string body = $"{{\"horizon_h\":{HorizonH},\"seed\":{Seed}," +
                      $"\"time_limit_s\":{timeLimitS}}}";

        var result = new HttpResult();
        yield return Post("/solve_milp", body, result, timeoutSeconds: 300);
        onDone?.Invoke(result.Ok ? result.Body : null);
    }

    /// <summary>Run GA + FCFS + MILP on same scenario and get gap analysis.</summary>
    public IEnumerator Compare(Action<CompareResponse> onDone)
    {
        string body = $"{{\"horizon_h\":{HorizonH},\"seed\":{Seed}}}";

        var result = new HttpResult();
        yield return Post("/compare", body, result, timeoutSeconds: 300);

        if (!result.Ok) { onDone?.Invoke(null); yield break; }
        onDone?.Invoke(JsonUtility.FromJson<CompareResponse>(result.Body));
    }

    // =====================================================================
    // Uncertainty
    // =====================================================================

    /// <summary>Update uncertainty params. Takes effect on next InitScenario.</summary>
    public IEnumerator SetUncertainty(
        float weatherProb = 0.05f,
        float stayNoiseFrac = 0.10f,
        int arrivalJitter = 0,
        float tugFailureProb = 0f,
        Action<bool> onDone = null)
    {
        string body = "{" +
            $"\"weather_prob\":{weatherProb}," +
            $"\"stay_noise_frac\":{stayNoiseFrac}," +
            $"\"arrival_jitter\":{arrivalJitter}," +
            $"\"tug_failure_prob\":{tugFailureProb}" +
            "}";

        var result = new HttpResult();
        yield return Post("/set_uncertainty", body, result);
        onDone?.Invoke(result.Ok);
    }

    // =====================================================================
    // Housekeeping
    // =====================================================================

    public IEnumerator HealthCheck(Action<HealthResponse> onDone)
    {
        var result = new HttpResult();
        yield return Get("/health", result);

        if (!result.Ok) { onDone?.Invoke(null); yield break; }
        onDone?.Invoke(JsonUtility.FromJson<HealthResponse>(result.Body));
    }

    public IEnumerator DeleteSession(string sessionId, Action<bool> onDone = null)
    {
        using var req = UnityWebRequest.Delete($"{ServerUrl}/session/{sessionId}");
        req.timeout = 5;
        yield return req.SendWebRequest();
        onDone?.Invoke(req.result == UnityWebRequest.Result.Success);
    }

    // =====================================================================
    // HTTP helpers — yield the request, write result into HttpResult object
    // No lambdas with yield anywhere below
    // =====================================================================

    private IEnumerator Get(string endpoint, HttpResult result)
    {
        using var req = UnityWebRequest.Get(ServerUrl + endpoint);
        req.timeout = 10;
        yield return req.SendWebRequest();

        result.Ok = req.result == UnityWebRequest.Result.Success;
        result.Body = result.Ok ? req.downloadHandler.text : req.error;

        if (!result.Ok)
        {
            Debug.LogError($"[NavalApi] GET {endpoint}: {req.error}");
            OnApiError?.Invoke(req.error);
        }
    }

    private IEnumerator Post(string endpoint, string jsonBody,
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
        {
            Debug.LogError($"[NavalApi] POST {endpoint}: {req.error}");
            OnApiError?.Invoke(req.error);
        }
    }
}