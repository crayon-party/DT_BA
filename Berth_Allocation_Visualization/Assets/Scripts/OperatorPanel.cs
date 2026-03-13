/*
 * OperatorPanel.cs
 * ================
 * Combined operator control panel for the Naval Berth Digital Twin.
 *
 * Two sections:
 *
 * A) SCENARIO SETUP (sent to Python on Apply)
 *      - Seed
 *      - Horizon (hours)
 *      - Number of vessels per type (K / F / L / P)
 *      - Mode (GA / FCFS)
 *
 * B) WEATHER CONTROL (sent to Python on Reschedule)
 *      - Weather level dropdown (Clear / Light / Moderate / Storm)
 *      - Duration (hours)
 *      - Reschedule button → POST /set_weather_event
 *      - Result display (message + before/after metrics + vessel list)
 *
 * Setup:
 *   1. Create a UI Panel in Canvas, name it "OperatorPanel"
 *   2. Add this component to it
 *   3. Wire all fields in Inspector
 *   4. Drag your APIClient GameObject into the BerthController field
 *   5. Wire buttons:
 *        Apply Scenario button  → OperatorPanel.OnApplyScenarioClicked
 *        Reschedule button      → OperatorPanel.OnRescheduleClicked
 *        Toggle panel button    → OperatorPanel.OnTogglePanel
 */

using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using TMPro;

public class OperatorPanel : MonoBehaviour
{
    // ── References ────────────────────────────────────────────────────────────
    [Header("Controller")]
    public BerthController berthController;

    // ── Scenario inputs ───────────────────────────────────────────────────────
    [Header("Scenario Inputs")]
    public TMP_InputField seedInput;
    public TMP_InputField horizonInput;
    public TMP_InputField vesselCountKInput;   // Destroyer (K)
    public TMP_InputField vesselCountFInput;   // Frigate (F)
    public TMP_InputField vesselCountLInput;   // Landing (L)
    public TMP_InputField vesselCountPInput;   // Patrol (P)
    public TMP_Dropdown modeDropdown;        // GA / FCFS
    public Button SetScenarioButton;

    // ── Weather inputs ────────────────────────────────────────────────────────
    [Header("Weather Control")]
    public TMP_Dropdown weatherDropdown;     // Clear/Light/Moderate/Storm
    public TMP_InputField durationInput;       // hours
    public Button rescheduleButton;

    // ── Result display ────────────────────────────────────────────────────────
    [Header("Result Display")]
    public GameObject resultSection;       // parent object to show/hide
    public TMP_Text resultMessageText;
    public TMP_Text resultDelayText;
    public TMP_Text resultShiftingText;
    public TMP_Text resultAffectedText;
    public TMP_Text resultDetailText;

    // ── Panel toggle ──────────────────────────────────────────────────────────
    [Header("Panel")]
    public GameObject panelContent;        // the inner panel to show/hide
    public TMP_Text statusText;          // small status line at top

    // ── Defaults ─────────────────────────────────────────────────────────────
    private const int DEFAULT_SEED = 42;
    private const int DEFAULT_HORIZON = 168;
    private const float DEFAULT_DURATION = 8f;

    // =========================================================================
    // Unity lifecycle
    // =========================================================================

    void Start()
    {
        // Populate defaults
        if (seedInput != null) seedInput.text = DEFAULT_SEED.ToString();
        if (horizonInput != null) horizonInput.text = DEFAULT_HORIZON.ToString();
        if (durationInput != null) durationInput.text = DEFAULT_DURATION.ToString();

        // Mode dropdown options
        if (modeDropdown != null)
        {
            modeDropdown.ClearOptions();
            modeDropdown.AddOptions(new System.Collections.Generic.List<string> { "GA", "FCFS" });
        }

        // Weather dropdown options
        if (weatherDropdown != null)
        {
            weatherDropdown.ClearOptions();
            weatherDropdown.AddOptions(new System.Collections.Generic.List<string>
                { "0 — Clear", "1 — Light", "2 — Moderate", "3 — Storm" });
        }

        // Hide result section initially
        if (resultSection != null) resultSection.SetActive(false);

        SetStatus("Ready");
    }

    // =========================================================================
    // Panel toggle
    // =========================================================================

    public void OnTogglePanel()
    {
        if (panelContent == null) return;
        panelContent.SetActive(!panelContent.activeSelf);
    }

    // =========================================================================
    // A) Scenario — Apply button
    // =========================================================================

    public void OnApplyScenarioClicked()
    {
        if (berthController == null)
        {
            SetStatus("Error: BerthController not assigned.");
            return;
        }

        int seed = ParseInt(seedInput, DEFAULT_SEED);
        int horizon = ParseInt(horizonInput, DEFAULT_HORIZON);
        string mode = modeDropdown != null
            ? (modeDropdown.value == 0 ? "GA" : "FCFS")
            : "GA";

        SetStatus($"Loading: seed={seed}  horizon={horizon}h  mode={mode}...");

        // Pass vessel counts if provided
        int cK = ParseInt(vesselCountKInput, -1);
        int cF = ParseInt(vesselCountFInput, -1);
        int cL = ParseInt(vesselCountLInput, -1);
        int cP = ParseInt(vesselCountPInput, -1);

        bool customCounts = cK >= 0 || cF >= 0 || cL >= 0 || cP >= 0;

        if (customCounts)
            StartCoroutine(LoadWithCustomCounts(seed, horizon, mode, cK, cF, cL, cP));
        else
            berthController.LoadScenario(seed, horizon, mode);
    }

    private IEnumerator LoadWithCustomCounts(int seed, int horizon, string mode,
                                              int cK, int cF, int cL, int cP)
    {
        // Build vessel override JSON and send to server
        // Server's /init_scenario accepts a 'vessel_counts' field
        string serverUrl = berthController.ServerUrl;
        string sessionId = berthController.SessionId;

        // Build count overrides (only include types that were specified)
        var counts = new StringBuilder();
        counts.Append("{");
        bool first = true;
        void AddCount(string type, int count)
        {
            if (count < 0) return;
            if (!first) counts.Append(",");
            counts.Append($"\"{type}\":{count}");
            first = false;
        }
        AddCount("K", cK);
        AddCount("F", cF);
        AddCount("L", cL);
        AddCount("P", cP);
        counts.Append("}");

        string body = "{" +
            $"\"horizon_h\":{horizon}," +
            $"\"seed\":{seed}," +
            $"\"mode\":\"{mode}\"," +
            $"\"force_recalc\":true," +
            $"\"vessel_counts\":{counts}" +
            "}";

        byte[] bytes = Encoding.UTF8.GetBytes(body);
        using var req = new UnityWebRequest(serverUrl + "/init_scenario", "POST")
        {
            uploadHandler = new UploadHandlerRaw(bytes),
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = 30,
        };
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();

        if (req.result == UnityWebRequest.Result.Success)
        {
            SetStatus($"Scenario loaded: seed={seed}  horizon={horizon}h");
            berthController.StartAutoStep(berthController.playbackInterval);
        }
        else
        {
            // Fallback: load without custom counts
            Debug.LogWarning($"[OperatorPanel] Custom counts not supported yet, loading default.");
            berthController.LoadScenario(seed, horizon, mode);
            SetStatus($"Loaded (default counts): seed={seed}  horizon={horizon}h");
        }
    }

    // =========================================================================
    // B) Weather — Reschedule button
    // =========================================================================

    public void OnRescheduleClicked()
    {
        if (berthController == null)
        {
            SetStatus("Error: BerthController not assigned.");
            return;
        }

        int level = weatherDropdown != null ? weatherDropdown.value : 0;
        float duration = ParseFloat(durationInput, DEFAULT_DURATION);

        SetStatus($"Sending weather event: {WeatherName(level)} for {duration}h...");
        if (resultSection != null) resultSection.SetActive(false);

        StartCoroutine(SendWeatherEvent(level, duration));
    }

    private IEnumerator SendWeatherEvent(int level, float duration)
    {
        string serverUrl = berthController.ServerUrl;
        string sessionId = berthController.SessionId;

        if (string.IsNullOrEmpty(sessionId))
        {
            SetStatus("No active session — start simulation first.");
            yield break;
        }

        // Pause simulation
        berthController.StopAutoStep();

        string body = "{" +
            $"\"session_id\":\"{sessionId}\"," +
            $"\"level\":{level}," +
            $"\"duration_h\":{duration}" +
            "}";

        byte[] bytes = Encoding.UTF8.GetBytes(body);
        using var req = new UnityWebRequest(serverUrl + "/set_weather_event", "POST")
        {
            uploadHandler = new UploadHandlerRaw(bytes),
            downloadHandler = new DownloadHandlerBuffer(),
            timeout = 30,
        };
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();

        if (!req.result.Equals(UnityWebRequest.Result.Success))
        {
            SetStatus($"Error: {req.error}");
            berthController.StartAutoStep(berthController.playbackInterval);
            yield break;
        }

        var result = JsonUtility.FromJson<RescheduleResult>(req.downloadHandler.text);
        ShowResult(result);

        // Resume
        berthController.StartAutoStep(berthController.playbackInterval);
    }

    // =========================================================================
    // Result display
    // =========================================================================

    private void ShowResult(RescheduleResult result)
    {
        SetStatus(result.message);

        if (resultSection != null) resultSection.SetActive(true);

        if (resultMessageText != null)
            resultMessageText.text = result.message;

        if (resultDelayText != null)
        {
            float delta = result.metrics_after.delay - result.metrics_before.delay;
            string sign = delta >= 0 ? "+" : "";
            resultDelayText.text =
                $"Delay: {result.metrics_before.delay:F1}h → " +
                $"{result.metrics_after.delay:F1}h  ({sign}{delta:F1}h)";
        }

        if (resultShiftingText != null)
        {
            int delta = result.metrics_after.shifting - result.metrics_before.shifting;
            string sign = delta >= 0 ? "+" : "";
            resultShiftingText.text =
                $"Shifting: {result.metrics_before.shifting} → " +
                $"{result.metrics_after.shifting}  ({sign}{delta})";
        }

        int n = result.affected?.Length ?? 0;
        if (resultAffectedText != null)
            resultAffectedText.text = $"{n} vessel{(n == 1 ? "" : "s")} rescheduled";

        if (resultDetailText != null && result.affected != null)
        {
            var sb = new StringBuilder();
            foreach (var v in result.affected)
            {
                string action = v.action == "arrival_delayed" ? "Arrival" : "Departure";
                sb.AppendLine($"{v.id} ({v.type})  {action}: {v.from:F0}h → {v.to:F0}h");
            }
            resultDetailText.text = sb.ToString();
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private void SetStatus(string msg)
    {
        if (statusText != null) statusText.text = msg;
        Debug.Log($"Status: [OperatorPanel] {msg}");
    }

    private int ParseInt(TMP_InputField field, int fallback)
    {
        if (field == null || string.IsNullOrEmpty(field.text)) return fallback;
        return int.TryParse(field.text, out int v) ? v : fallback;
    }

    private float ParseFloat(TMP_InputField field, float fallback)
    {
        if (field == null || string.IsNullOrEmpty(field.text)) return fallback;
        return float.TryParse(field.text, out float v) ? v : fallback;
    }

    private static string WeatherName(int level) => level switch
    {
        0 => "Clear",
        1 => "Light",
        2 => "Moderate",
        3 => "Storm",
        _ => $"Level {level}"
    };
}