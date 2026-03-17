/*
 * OperatorPanel.cs
 * ================
 * Two-section operator control panel for the Naval Berth Digital Twin.
 *
 * ── SECTION A: NEW SIMULATION ────────────────────────────────────────────────
 * Sets up a fresh simulation. Always resets the current session.
 * Inputs: Seed, Horizon (h), Vessel counts (K/F/L/P), Mode (GA/FCFS)
 * Button: "Start New Simulation" → POST /init_scenario (force_recalc:true)
 *
 * ── SECTION B: INJECT EVENT ──────────────────────────────────────────────────
 * Intervenes in the live running simulation. Never resets.
 * Inputs: Weather level, Duration (h)
 * Button: "Reschedule" → POST /set_weather_event
 * Output: Before/after metrics + affected vessel list
 *
 * Setup
 * ─────
 * 1. Create a Canvas Panel, name it "OperatorPanel", add this component
 * 2. Build child UI (see hierarchy below) and wire fields in Inspector
 * 3. Wire buttons:
 *      Start New Simulation  → OperatorPanel.OnNewSimulationClicked
 *      Reschedule            → OperatorPanel.OnInjectWeatherClicked
 *
 * Suggested hierarchy:
 *   OperatorPanel
 *     PanelContent
 *       StatusText
 *       ── Section A ──
 *       SectionAHeader      ("NEW SIMULATION")
 *       SeedInput
 *       HorizonInput
 *       VesselCountK/F/L/P
 *       ModeDropdown
 *       StartButton
 *       ── Section B ──
 *       SectionBHeader      ("INJECT EVENT")
 *       WeatherDropdown
 *       DurationInput
 *       RescheduleButton
 *       ResultSection
 *         ResultMessageText
 *         ResultDelayText
 *         ResultShiftingText
 *         ResultAffectedText
 *         ResultDetailText
 */

using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using TMPro;

public class OperatorPanel : MonoBehaviour
{
    // ── Controller reference ──────────────────────────────────────────────────
    [Header("Controller")]
    public BerthController berthController;

    // ── Section A: New Simulation ─────────────────────────────────────────────
    [Header("Section A — New Simulation")]
    public TMP_InputField seedInput;
    public TMP_InputField horizonInput;
    public TMP_InputField vesselKInput;     // Destroyer
    public TMP_InputField vesselFInput;     // Frigate
    public TMP_InputField vesselLInput;     // Landing
    public TMP_InputField vesselPInput;     // Patrol
    public TMP_Dropdown modeDropdown;     // GA / FCFS

    // ── Weight sliders (Objective Weights) ─────────────────────────────────
    [Header("Weight Sliders (0-1, sum enforced)")]
    public UnityEngine.UI.Slider alphaSlider;   // shifting
    public UnityEngine.UI.Slider betaSlider;    // fatigue
    public UnityEngine.UI.Slider gammaSlider;   // delay
    public UnityEngine.UI.Slider deltaSlider;   // emissions
    public TMPro.TMP_Text weightsText;   // shows current α β γ δ
    public TMP_Text alphaLabel;
    public TMP_Text betaLabel;
    public TMP_Text gammaLabel;
    public TMP_Text deltaLabel;

    // ── Section B: Inject Event ───────────────────────────────────────────────
    [Header("Section B — Inject Event")]
    public TMP_Dropdown weatherDropdown;  // Clear / Light / Moderate / Storm
    public TMP_InputField durationInput;    // hours

    // ── Result display (Section B output) ────────────────────────────────────
    [Header("Result Display")]
    public GameObject resultSection;
    public TMP_Text resultMessageText;
    public TMP_Text resultDelayText;
    public TMP_Text resultShiftingText;
    public TMP_Text resultAffectedText;
    public TMP_Text resultDetailText;

    // ── Status ───────────────────────────────────────────────────────────────
    [Header("Panel")]
    public TMP_Text statusText;

    // ── Defaults ─────────────────────────────────────────────────────────────
    private const int DEFAULT_SEED = 42;
    private const int DEFAULT_HORIZON = 168;
    private const float DEFAULT_DURATION = 8f;

    // =========================================================================
    // Unity lifecycle
    // =========================================================================

    void Start()
    {
        if (berthController == null)
            berthController = FindFirstObjectByType<BerthController>();

        // Populate defaults
        if (seedInput != null) seedInput.text = DEFAULT_SEED.ToString();
        if (horizonInput != null) horizonInput.text = DEFAULT_HORIZON.ToString();
        if (durationInput != null) durationInput.text = DEFAULT_DURATION.ToString();

        // Section A mode dropdown
        if (modeDropdown != null)
        {
            modeDropdown.ClearOptions();
            modeDropdown.AddOptions(new System.Collections.Generic.List<string> { "GA", "FCFS" });
        }

        // Section B weather dropdown
        if (weatherDropdown != null)
        {
            weatherDropdown.ClearOptions();
            weatherDropdown.AddOptions(new System.Collections.Generic.List<string>
                { "0 — Clear", "1 — Light", "2 — Moderate", "3 — Storm" });
        }

        if (resultSection != null) resultSection.SetActive(false);

        // Wire weight sliders
        /*if (alphaSlider != null) alphaSlider.onValueChanged.AddListener(_ => UpdateWeightsText(
      alphaSlider.value, betaSlider.value, gammaSlider.value, deltaSlider.value));
        if (betaSlider != null) betaSlider.onValueChanged.AddListener(_ => UpdateWeightsText(
           alphaSlider.value, betaSlider.value, gammaSlider.value, deltaSlider.value));
        if (gammaSlider != null) gammaSlider.onValueChanged.AddListener(_ => UpdateWeightsText(
            alphaSlider.value, betaSlider.value, gammaSlider.value, deltaSlider.value));
        if (deltaSlider != null) deltaSlider.onValueChanged.AddListener(_ => UpdateWeightsText(
            alphaSlider.value, betaSlider.value, gammaSlider.value, deltaSlider.value));*/

        if (alphaSlider != null) alphaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged(sendToServer: false));
        if (betaSlider != null) betaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged(sendToServer: false));
        if (gammaSlider != null) gammaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged(sendToServer: false));
        if (deltaSlider != null) deltaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged(sendToServer: false));

        UpdateWeightsText();
        if (resultSection != null) resultSection.SetActive(false);
        SetStatus("Ready");
    }

    // =========================================================================
    // Section A — New Simulation
    // Always resets: new parameters = new experiment
    // =========================================================================

    public void OnNewSimulationClicked()
    {
        if (berthController == null) { SetStatus("Error: BerthController not assigned."); return; }

        int seed = ParseInt(seedInput, DEFAULT_SEED);
        int horizon = ParseInt(horizonInput, DEFAULT_HORIZON);
        string mode = modeDropdown != null && modeDropdown.value == 1 ? "FCFS" : "GA";

        // Vessel count overrides — only include types that were explicitly set
        int cK = ParseInt(vesselKInput, -1);
        int cF = ParseInt(vesselFInput, -1);
        int cL = ParseInt(vesselLInput, -1);
        int cP = ParseInt(vesselPInput, -1);

        bool hasCustomCounts = cK >= 0 || cF >= 0 || cL >= 0 || cP >= 0;

        SetStatus($"Starting new simulation: seed={seed}  horizon={horizon}h  mode={mode}...");
        if (resultSection != null) resultSection.SetActive(false);

        // Wire weight sliders
        //if (alphaSlider != null) alphaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
       // if (betaSlider != null) betaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
        //if (gammaSlider != null) gammaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
       // if (deltaSlider != null) deltaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
        UpdateWeightsText();

        // Always route through BerthController so SessionId and auto-step update correctly
        berthController.LoadScenario(seed, horizon, mode, cK, cF, cL, cP);
    }


    // =========================================================================
    // Section B — Inject Weather Event
    // Never resets: mid-run intervention, GA reschedules from current tick
    // =========================================================================

    public void OnInjectWeatherClicked()
    {
        if (berthController == null) { SetStatus("Error: BerthController not assigned."); return; }
        if (string.IsNullOrEmpty(berthController.SessionId))
        {
            SetStatus("No active session — start a simulation first.");
            return;
        }

        int level = weatherDropdown != null ? weatherDropdown.value : 0;
        float duration = ParseFloat(durationInput, DEFAULT_DURATION);

        SetStatus($"Injecting: {WeatherName(level)} for {duration}h — GA rescheduling...");
        if (resultSection != null) resultSection.SetActive(false);

        // Wire weight sliders
        //if (alphaSlider != null) alphaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
       // if (betaSlider != null) betaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
       // if (gammaSlider != null) gammaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
        //if (deltaSlider != null) deltaSlider.onValueChanged.AddListener(_ => OnAnyWeightChanged());
        //UpdateWeightsText();

        StartCoroutine(InjectWeatherEvent(level, duration));
    }

    private IEnumerator InjectWeatherEvent(int level, float duration)
    {
        bool wasRunning = berthController.IsRunning;
        berthController.StopAutoStep();

        string body = "{" +
            $"\"session_id\":\"{berthController.SessionId}\"," +
            $"\"level\":{level}," +
            $"\"duration_h\":{duration}" +
            "}";

        byte[] bytes = Encoding.UTF8.GetBytes(body);
        using var req = new UnityWebRequest(berthController.ServerUrl + "/set_weather_event", "POST")
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
            if (wasRunning) berthController.StartAutoStep(berthController.playbackInterval);
            yield break;
        }

        var result = JsonUtility.FromJson<RescheduleResult>(req.downloadHandler.text);
        ShowRescheduleResult(result);

        if (wasRunning) berthController.StartAutoStep(berthController.playbackInterval);
    }

    // =========================================================================
    // Result display
    // =========================================================================

    private void ShowRescheduleResult(RescheduleResult result)
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
                $"Delay:    {result.metrics_before.delay:F1}h → " +
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

    // ── Weight slider handler ────────────────────────────────────────────────

    private void OnAnyWeightChanged(bool sendToServer = true)
    {
        float a = alphaSlider != null ? alphaSlider.value : 0.25f;
        float b = betaSlider != null ? betaSlider.value : 0.25f;
        float g = gammaSlider != null ? gammaSlider.value : 0.25f;
        float d = deltaSlider != null ? deltaSlider.value : 0.25f;
        float total = a + b + g + d;
        if (total <= 0) return;
        a /= total; b /= total; g /= total; d /= total;
        UpdateWeightsText(a, b, g, d);
        if (sendToServer)
            berthController?.OnWeightsChanged(a, b, g, d);
    }

    private void UpdateWeightsText(float a = 0.25f, float b = 0.25f,
                                    float g = 0.25f, float d = 0.25f)
    {
        if (weightsText == null) return;
        
        weightsText.text = "α=" + a.ToString("F2") +
                           "  β=" + b.ToString("F2") +
                           "  γ=" + g.ToString("F2") +
                           "  δ=" + d.ToString("F2");
    }

    private void SetStatus(string msg)
    {
        if (statusText != null) statusText.text = msg;
        Debug.Log($"[OperatorPanel] {msg}");
    }
    public void OnApplyWeightsClicked()
    {
        OnAnyWeightChanged(sendToServer: true);
        SetStatus($"Weights applied");
    }

    private int ParseInt(TMP_InputField f, int def) =>
        f != null && int.TryParse(f.text, out int v) ? v : def;

    private float ParseFloat(TMP_InputField f, float def) =>
        f != null && float.TryParse(f.text, out float v) ? v : def;

    private static string WeatherName(int level) => level switch
    {
        0 => "Clear",
        1 => "Light",
        2 => "Moderate",
        3 => "Storm",
        _ => $"Level {level}"
    };
}




/*
 * OperatorPanel.cs
 * ================
 * Two-section operator control panel for the Naval Berth Digital Twin.
 *
 * ── SECTION A: NEW SIMULATION ────────────────────────────────────────────────
 * Sets up a fresh simulation. Always resets the current session.
 * Inputs: Seed, Horizon (h), Vessel counts (K/F/L/P), Mode (GA/FCFS)
 * Button: "Start New Simulation" → POST /init_scenario (force_recalc:true)
 *
 * ── SECTION B: INJECT EVENT ──────────────────────────────────────────────────
 * Intervenes in the live running simulation. Never resets.
 * Inputs: Weather level, Duration (h)
 * Button: "Reschedule" → POST /set_weather_event
 * Output: Before/after metrics + affected vessel list
 *
 * Setup
 * ─────
 * 1. Create a Canvas Panel, name it "OperatorPanel", add this component
 * 2. Build child UI (see hierarchy below) and wire fields in Inspector
 * 3. Wire buttons:
 *      Start New Simulation  → OperatorPanel.OnNewSimulationClicked
 *      Reschedule            → OperatorPanel.OnInjectWeatherClicked
 *
 * Suggested hierarchy:
 *   OperatorPanel
 *     PanelContent
 *       StatusText
 *       ── Section A ──
 *       SectionAHeader      ("NEW SIMULATION")
 *       SeedInput
 *       HorizonInput
 *       VesselCountK/F/L/P
 *       ModeDropdown
 *       StartButton
 *       ── Section B ──
 *       SectionBHeader      ("INJECT EVENT")
 *       WeatherDropdown
 *       DurationInput
 *       RescheduleButton
 *       ResultSection
 *         ResultMessageText
 *         ResultDelayText
 *         ResultShiftingText
 *         ResultAffectedText
 *         ResultDetailText
 */
/*
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using TMPro;

public class OperatorPanel : MonoBehaviour
{
   // ── Controller reference ──────────────────────────────────────────────────
   [Header("Controller")]
   public BerthController berthController;

   // ── Section A: New Simulation ─────────────────────────────────────────────
   [Header("Section A — New Simulation")]
   public TMP_InputField seedInput;
   public TMP_InputField horizonInput;
   public TMP_InputField vesselKInput;     // Destroyer
   public TMP_InputField vesselFInput;     // Frigate
   public TMP_InputField vesselLInput;     // Landing
   public TMP_InputField vesselPInput;     // Patrol
   public TMP_Dropdown   modeDropdown;     // GA / FCFS

   // ── Section B: Inject Event ───────────────────────────────────────────────
   [Header("Section B — Inject Event")]
   public TMP_Dropdown   weatherDropdown;  // Clear / Light / Moderate / Storm
   public TMP_InputField durationInput;    // hours

   // ── Result display (Section B output) ────────────────────────────────────
   [Header("Result Display")]
   public GameObject  resultSection;
   public TMP_Text    resultMessageText;
   public TMP_Text    resultDelayText;
   public TMP_Text    resultShiftingText;
   public TMP_Text    resultAffectedText;
   public TMP_Text    resultDetailText;

   // ── Status ───────────────────────────────────────────────────────────────
   [Header("Panel")]
   public TMP_Text   statusText;

   // ── Defaults ─────────────────────────────────────────────────────────────
   private const int   DEFAULT_SEED     = 42;
   private const int   DEFAULT_HORIZON  = 168;
   private const float DEFAULT_DURATION = 8f;

   // =========================================================================
   // Unity lifecycle
   // =========================================================================

   void Start()
   {
       if (berthController == null)
           berthController = FindFirstObjectByType<BerthController>();

       // Populate defaults
       if (seedInput    != null) seedInput.text    = DEFAULT_SEED.ToString();
       if (horizonInput != null) horizonInput.text = DEFAULT_HORIZON.ToString();
       if (durationInput != null) durationInput.text = DEFAULT_DURATION.ToString();

       // Section A mode dropdown
       if (modeDropdown != null)
       {
           modeDropdown.ClearOptions();
           modeDropdown.AddOptions(new System.Collections.Generic.List<string> { "GA", "FCFS" });
       }

       // Section B weather dropdown
       if (weatherDropdown != null)
       {
           weatherDropdown.ClearOptions();
           weatherDropdown.AddOptions(new System.Collections.Generic.List<string>
               { "0 — Clear", "1 — Light", "2 — Moderate", "3 — Storm" });
       }

       if (resultSection != null) resultSection.SetActive(false);
       SetStatus("Ready");
   }

   // =========================================================================
   // Section A — New Simulation
   // Always resets: new parameters = new experiment
   // =========================================================================

   public void OnNewSimulationClicked()
   {
       if (berthController == null) { SetStatus("Error: BerthController not assigned."); return; }

       int    seed    = ParseInt(seedInput,    DEFAULT_SEED);
       int    horizon = ParseInt(horizonInput, DEFAULT_HORIZON);
       string mode    = modeDropdown != null && modeDropdown.value == 1 ? "FCFS" : "GA";

       // Vessel count overrides — only include types that were explicitly set
       int cK = ParseInt(vesselKInput, -1);
       int cF = ParseInt(vesselFInput, -1);
       int cL = ParseInt(vesselLInput, -1);
       int cP = ParseInt(vesselPInput, -1);

       bool hasCustomCounts = cK >= 0 || cF >= 0 || cL >= 0 || cP >= 0;

       SetStatus($"Starting new simulation: seed={seed}  horizon={horizon}h  mode={mode}...");
       if (resultSection != null) resultSection.SetActive(false);

       // Always route through BerthController so SessionId and auto-step update correctly
       berthController.LoadScenario(seed, horizon, mode, cK, cF, cL, cP);
   }


   // =========================================================================
   // Section B — Inject Weather Event
   // Never resets: mid-run intervention, GA reschedules from current tick
   // =========================================================================

   public void OnInjectWeatherClicked()
   {
       if (berthController == null) { SetStatus("Error: BerthController not assigned."); return; }
       if (string.IsNullOrEmpty(berthController.SessionId))
       {
           SetStatus("No active session — start a simulation first.");
           return;
       }

       int   level    = weatherDropdown != null ? weatherDropdown.value : 0;
       float duration = ParseFloat(durationInput, DEFAULT_DURATION);

       SetStatus($"Injecting: {WeatherName(level)} for {duration}h — GA rescheduling...");
       if (resultSection != null) resultSection.SetActive(false);

       StartCoroutine(InjectWeatherEvent(level, duration));
   }

   private IEnumerator InjectWeatherEvent(int level, float duration)
   {
       bool wasRunning = berthController.IsRunning;
       berthController.StopAutoStep();

       string body = "{" +
           $"\"session_id\":\"{berthController.SessionId}\"," +
           $"\"level\":{level}," +
           $"\"duration_h\":{duration}" +
           "}";

       byte[] bytes = Encoding.UTF8.GetBytes(body);
       using var req = new UnityWebRequest(berthController.ServerUrl + "/set_weather_event", "POST")
       {
           uploadHandler   = new UploadHandlerRaw(bytes),
           downloadHandler = new DownloadHandlerBuffer(),
           timeout         = 30,
       };
       req.SetRequestHeader("Content-Type", "application/json");
       yield return req.SendWebRequest();

       if (!req.result.Equals(UnityWebRequest.Result.Success))
       {
           SetStatus($"Error: {req.error}");
           if (wasRunning) berthController.StartAutoStep(berthController.playbackInterval);
           yield break;
       }

       var result = JsonUtility.FromJson<RescheduleResult>(req.downloadHandler.text);
       ShowRescheduleResult(result);

       if (wasRunning) berthController.StartAutoStep(berthController.playbackInterval);
   }

   // =========================================================================
   // Result display
   // =========================================================================

   private void ShowRescheduleResult(RescheduleResult result)
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
               $"Delay:    {result.metrics_before.delay:F1}h → " +
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
       Debug.Log($"[OperatorPanel] {msg}");
   }

   private int   ParseInt(TMP_InputField f, int   def) =>
       f != null && int.TryParse(f.text, out int v)     ? v : def;

   private float ParseFloat(TMP_InputField f, float def) =>
       f != null && float.TryParse(f.text, out float v) ? v : def;

   private static string WeatherName(int level) => level switch
   {
       0 => "Clear", 1 => "Light", 2 => "Moderate", 3 => "Storm", _ => $"Level {level}"
   };
}*/