using System.IO;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class JsonPlayer : MonoBehaviour
{
    [Header("Setup")]
    public PortVisualizer visualizer;
    [Tooltip("Simulation speed scaling factor. Default = 5, range 1–20.")]
    [Range(1f, 20f)]
    public float simSpeed = 5f;
    public Slider speedSlider;       // optional, assign in Inspector
    public TMP_Text speedText;           // optional, display speed

    StateMessage[] snapshots;
    int currentIndex = 0;
    float timer = 0f;

    void Start()
    {
        LoadSnapshots();
        if (speedSlider != null)
        {
            speedSlider.minValue = 1f;
            speedSlider.maxValue = 20f;
            speedSlider.value = simSpeed; 
            speedSlider.onValueChanged.AddListener(OnSpeedChanged);
        }

        if (speedText != null)
            speedText.text = $"Speed: {simSpeed:F1}x";
    }

        void Update()
    {
        if (snapshots == null || snapshots.Length == 0) return;

        // Advance simulation time scaled by simSpeed
        timer += Time.deltaTime * simSpeed;

        // Clamp timer to last snapshot
        if (timer >= snapshots.Length - 1)
            timer = snapshots.Length - 1;

        int index = Mathf.Min(Mathf.FloorToInt(timer), snapshots.Length - 1);

        if (index != currentIndex)
        {
            currentIndex = index;
            visualizer.ApplyState(snapshots[currentIndex]);

            // Optional debug
            if (currentIndex % 100 == 0)
            {
                Debug.Log($"Time {snapshots[currentIndex].time}: Ships at berth: {CountAtBerth(snapshots[currentIndex].ships)}");
            }
        }
    }

    void OnSpeedChanged(float value)
    {
        simSpeed = value;
        if (speedText != null)
            speedText.text = $"Speed: {simSpeed:F2}x";
    }

    void LoadSnapshots()
    {
        string filename = "naval_snapshots.json";

#if UNITY_EDITOR
        string path = Path.Combine(Application.dataPath, "StreamingAssets", filename);
#else
        string path = Path.Combine(Application.streamingAssetsPath, filename);
#endif

        Debug.Log($"Loading from: {path}");

        if (!File.Exists(path))
        {
            Debug.LogError($"File not found: {path}");
            Debug.LogError("Copy naval_snapshots.json to Assets/StreamingAssets/");
            return;
        }

        string jsonText = File.ReadAllText(path);
        snapshots = JsonHelper.FromJson<StateMessage>(jsonText);

        Debug.Log($"Loaded {snapshots.Length} snapshots");

        if (snapshots.Length > 0)
        {
            visualizer.ApplyState(snapshots[0]);
        }
    }

    int CountAtBerth(ShipState[] ships)
    {
        return System.Array.FindAll(
            ships,
            s => !string.IsNullOrEmpty(s.pier) && s.layer >= 0
        ).Length;
    }
}