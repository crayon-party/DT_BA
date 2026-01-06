using System.IO;
using UnityEngine;

public class JsonPlayer : MonoBehaviour 
{
    [Header("Setup")]
    public PortVisualizer visualizer;
    public float replaySpeed = 50f;  // snapshots per second
    
    StateMessage[] snapshots;
    int currentIndex = 0;
    float timer = 0f;
    
    void Start() {
        LoadSnapshots();
    }
    
    void LoadSnapshots() 
    {
    string filename = "naval_snapshots.json";
 
    // Editor: use Assets/StreamingAssets directly
    string path;
    #if UNITY_EDITOR
        path = System.IO.Path.Combine(Application.dataPath, "StreamingAssets", filename);
    #else
        path = System.IO.Path.Combine(Application.streamingAssetsPath, filename);
    #endif
    
    Debug.Log($"Loading from: {path}");
    
    if (!System.IO.File.Exists(path)) {
        Debug.LogError($"File not found: {path}");
        Debug.LogError("Copy naval_snapshots.json to Assets/StreamingAssets/");
        return;
    }
    
    string jsonText = System.IO.File.ReadAllText(path);
    //SnapshotWrapper wrapper = JsonUtility.FromJson<SnapshotWrapper>(jsonText);
    snapshots = JsonHelper.FromJson<StateMessage>(jsonText);
    
    Debug.Log($"✅ Loaded {snapshots.Length} snapshots");
    if (snapshots.Length > 0) {
        visualizer.ApplyState(snapshots[0]);
    }
}

    
    void Update() {
        if (snapshots == null || snapshots.Length == 0) return;
        
        timer += Time.deltaTime * replaySpeed;
        int targetIndex = Mathf.FloorToInt(timer);
        
        if (targetIndex >= snapshots.Length) {
            targetIndex = snapshots.Length - 1;  // end of simulation
        }
        
        if (targetIndex != currentIndex) {
            currentIndex = targetIndex;
            visualizer.ApplyState(snapshots[currentIndex]);
            
            // Debug info
            if (currentIndex % 100 == 0) {
                Debug.Log($"Time {snapshots[currentIndex].time}: " +
                         $"Ships at berth: {CountAtBerth(snapshots[currentIndex].ships)}");
            }
        }
    }
    
    int CountAtBerth(ShipState[] ships) {
        return System.Array.FindAll(ships, s => s.pier != null).Length;
    }
}
