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
    public UnityEngine.UI.Image nightTint;
    public UnityEngine.UI.Image weatherTint;

    private static readonly string[] WeatherNames = { "Clear", "Light", "Moderate", "Storm" };

    // One ShipView per physical ship
    private Dictionary<string, ShipView> ships = new Dictionary<string, ShipView>();

    private string GetPhysicalShipId(ShipState state) => state.id;

    public void ApplyState(StateMessage state)
    {
        UpdateShips(state.ships);
        UpdateGlobalUI(state);
    }

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

    private ShipView CreateShip(ShipState state)
    {
        GameObject go = Instantiate(shipPrefab);
        go.name = $"Ship_{GetPhysicalShipId(state)}";
        go.transform.localScale = new Vector3(30f, 10f, 80f);
        return go.GetComponent<ShipView>();
    }

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
                pos.y = 0.5f;
                shipView.transform.position = pos;
                shipView.transform.rotation = Quaternion.identity;
                return;
            }
        }

        // === WAITING / ANCHORAGE ===
        if (anchorageOrigin != null)
        {
            int idHash = Mathf.Abs(state.id.GetHashCode());
            int col = idHash % anchorageColumns;
            int row = (idHash / anchorageColumns) % anchorageColumns;
            Vector3 offset = new Vector3(col * anchorageSpacing, 0.5f, row * anchorageSpacing);
            shipView.transform.position = anchorageOrigin.position + offset;
            shipView.transform.rotation = Quaternion.identity;
        }
        else
        {
            shipView.transform.position = new Vector3(0f, 0.5f, 0f);
            shipView.transform.rotation = Quaternion.identity;
        }
    }

    private void UpdateGlobalUI(StateMessage state)
    {
        // ── Time — convert hours to Day X  HH:MM ─────────────────────────────
        if (timeText != null)
        {
            int totalHours = state.time;
            int day = (totalHours / 24) + 1;
            int hour = totalHours % 24;
            timeText.text = $"Day {day}  {hour:D2}:00";
        }

        // ── Weather ───────────────────────────────────────────────────────────
        if (weatherText != null)
        {
            string name = WeatherNames[Mathf.Clamp(state.weather, 0, 3)];
            weatherText.text = $"Weather: {name}";
        }

        // ── Night / Day ───────────────────────────────────────────────────────
        if (nightText != null)
            nightText.text = state.is_night ? "Night" : "Day";

        // ── Lunch ─────────────────────────────────────────────────────────────
        if (lunchText != null)
            lunchText.text = state.is_lunch ? "Lunch Break" : "Working";

        // ── Ships at berth ────────────────────────────────────────────────────
        if (shipsAtBerthText != null && state.ships != null)
        {
            int atBerth = System.Array.FindAll(
                state.ships, s => !string.IsNullOrEmpty(s.pier) && s.layer >= 0).Length;
            shipsAtBerthText.text = $"Ships at Berth: {atBerth}";
        }

        // ── Tugs ──────────────────────────────────────────────────────────────
        if (tugStatusText != null && state.tugs != null)
        {
            var sb = new System.Text.StringBuilder();
            foreach (var tug in state.tugs)
                sb.AppendLine($"{tug.id}: {tug.status}");
            tugStatusText.text = sb.ToString();
        }

        // ── Metrics ───────────────────────────────────────────────────────────
        if (metricsText != null && state.metrics != null)
        {
            metricsText.text =
                $"Shifting: {state.metrics.shifting}\n" +
                $"Fatigue:  {state.metrics.fatigue:F1}\n" +
                $"Delay:    {state.metrics.delay:F1}h";
        }

        UpdateScreenEffects(state);
    }

    private void UpdateScreenEffects(StateMessage state)
    {
        // Night tint
        if (nightTint != null)
        {
            Color c = Color.black;
            c.a = state.is_night ? 0.4f : 0f;
            nightTint.color = c;
        }

        // Weather tint
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