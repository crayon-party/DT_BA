using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

[System.Serializable]
public class PierSlots
{
    public Transform[] slots;
}

public class PortVisualizer : MonoBehaviour
{
    [Header("Pier References")]
    public Transform[] pierTransforms;          // P1-P8
    public PierSlots[] slotPositions;           // slotPositions[pier][layer]

    [Header("Prefabs")]
    public GameObject shipPrefab;

    [Header("Waiting Area")]
    public Transform anchorageOrigin;
    public float anchorageSpacing = 4f;
    public int anchorageColumns = 10;

    [Header("UI Elements")]
    public TMP_Text timeText;
    public TMP_Text weatherText;
    public TMP_Text nightText;
    public TMP_Text lunchText;
    public TMP_Text shipsAtBerthText;
    public TMP_Text tugStatusText;
    public TMP_Text metricsText;

    [Header("Screen Effects")]
    public UnityEngine.UI.Image nightTint;   // black
    public UnityEngine.UI.Image weatherTint; // white

    // One ShipView per physical ship
    private Dictionary<string, ShipView> ships = new Dictionary<string, ShipView>();

    // Stable ID stripping time step
    private string GetPhysicalShipId(ShipState state)
    {
        //if (string.IsNullOrEmpty(state.id)) return "";
        //int idx = state.id.IndexOf('_');
        //return idx > 0 ? state.id.Substring(0, idx) : state.id;
        return state.id;
    }

    // Apply a full snapshot
    public void ApplyState(StateMessage state)
    {
        UpdateShips(state.ships);
        UpdateGlobalUI(state);
    }

    // Update or create ships
    private void UpdateShips(ShipState[] shipStates)
    {
        foreach (var state in shipStates)
        {
            string pid = GetPhysicalShipId(state);

            if (!ships.TryGetValue(pid, out ShipView ship))
            {
                ship = CreateShip(state);
                ships[pid] = ship;
            }

            PositionShip(ship, state);
        }
    }

    // Instantiate a new ship
    private ShipView CreateShip(ShipState state)
    {
        GameObject go = Instantiate(shipPrefab);
        go.name = $"Ship_{GetPhysicalShipId(state)}";

        // Only scale once
        go.transform.localScale = new Vector3(30f, 10f, 80f);

        return go.GetComponent<ShipView>();
    }

    // Update ship position, rotation, and state
    private void PositionShip(ShipView shipView, ShipState state)
    {
        shipView.SetState(state);

        // === AT BERTH ===
        if (!string.IsNullOrEmpty(state.pier) && state.layer >= 0)
        {
            int pierIdx = int.Parse(state.pier.Substring(1)) - 1;
            int slotIdx = state.layer;

            if (pierIdx >= 0 &&
                pierIdx < slotPositions.Length &&
                slotPositions[pierIdx] != null &&
                slotIdx >= 0 &&
                slotIdx < slotPositions[pierIdx].slots.Length)
            {
                Vector3 pos = slotPositions[pierIdx].slots[slotIdx].position;
                pos.y = 0.5f; // safe above ground
                shipView.transform.position = pos;
                shipView.transform.rotation = Quaternion.identity;
                return;
            }
        }

        // === WAITING / ANCHORAGE ===
        if (anchorageOrigin != null)
        {
            int idHash = Mathf.Abs(state.id.GetHashCode());
            float spacing = anchorageSpacing;

            int col = idHash % anchorageColumns;
            int row = (idHash / anchorageColumns) % anchorageColumns; // MOD to keep in bounds

            Vector3 offset = new Vector3(col * spacing, 0.5f, row * spacing);
            shipView.transform.position = anchorageOrigin.position + offset;
            shipView.transform.rotation = Quaternion.identity; // flat, not rotated
        }
        else
        {
            shipView.transform.position = new Vector3(0.0f, 0.5f, 0.0f);
            shipView.transform.rotation = Quaternion.identity;
        }
    }

    // Placeholder for UI updates (optional)
    private void UpdateGlobalUI(StateMessage state)
    {
        // Weather, night/day indicators, KPIs, etc.

        // Time
        if (timeText != null)
            timeText.text = $"Time: {state.time} mins";

        // Weather
        if (weatherText != null)
            weatherText.text = $"Weather: {state.weather}";

        // Night / Day
        if (nightText != null)
            nightText.text = state.is_night ? "Night" : "Day";

        // Lunch
        if (lunchText != null)
            lunchText.text = state.is_lunch ? "Lunch Time" : "Working";

        // Ships at berth
        if (shipsAtBerthText != null && state.ships != null)
        {
            int atBerth = System.Array.FindAll(state.ships, s => !string.IsNullOrEmpty(s.pier) && s.layer >= 0).Length;
            shipsAtBerthText.text = $"Ships at Berth: {atBerth}";
        }

        // Tugs status
        if (tugStatusText != null && state.tugs != null)
        {
            string tugInfo = "";
            foreach (var tug in state.tugs)
            {
                tugInfo += $"{tug.id}: {tug.status} (Free: {tug.free_time} mins)\n";
            }
            tugStatusText.text = tugInfo;
        }

        // Metrics
        if (metricsText != null && state.metrics != null)
        {
            metricsText.text =
                $"Shifting: {state.metrics.shifting}\n" +
                $"Fatigue: {state.metrics.fatigue:F2}\n" +
                $"Delay: {state.metrics.delay:F2}";
        }
        UpdateScreenEffects(state);
    }
    private void UpdateScreenEffects(StateMessage state)
    {
        // --- Night ---
        if (nightTint != null)
        {
            Color c = Color.black;
            c.a = state.is_night ? 0.4f : 0f;
            nightTint.color = c;
        }

        // --- Weather ---
        if (weatherTint != null)
        {
            float alpha = state.weather switch
            {
                0 => 0f,
                1 => 0.05f,
                2 => 0.11f,
                3 => 0.18f,
                _ => 0.2f
            };
            Color c = Color.white;
            c.a = alpha;
            weatherTint.color = c;
        }
    }
}
