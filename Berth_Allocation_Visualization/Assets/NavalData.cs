using System;
using UnityEngine;

[Serializable]
public class StateMessage {
    public string type;
    public int time;
    public int weather;
    public bool is_night;
    public bool is_lunch;
    public ShipState[] ships;
    public TugState[] tugs;
    public Metrics metrics;
}

[Serializable]
public class ShipState {
    public string id;
    public string type;
    public string status;
    public string pier;        // "P1", "P2", "" for null
    public int layer;          // 0,1,2 or -1 for "no layer"
    public int arr_time;
    public int dep_planned;    // 0 if null
    public int dep_actual;     // 0 if null
}

[Serializable]
public class TugState {
    public string id;
    public string status;
    public int free_time;
}

[Serializable]
public class Metrics {
    public int shifting;
    public float fatigue;
    public float delay;
}

[Serializable]
public class SnapshotWrapper {
    public StateMessage[] snapshots;
}
