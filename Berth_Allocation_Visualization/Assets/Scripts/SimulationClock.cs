/*
 * SimulationClock.cs
 * ==================
 * Displays simulation time from the live SimSnapshot.
 * Also controls playback speed via the Speed slider.
 *
 * Setup:
 *  1. Add this component to your SimulationClock GameObject (already in Hierarchy)
 *  2. Wire fields in Inspector:
 *       BerthController  → drag your APIClient GameObject
 *       TimeText         → drag your Time TMP text
 *  3. Speed slider OnValueChanged → SimulationClock.OnSpeedSliderChanged
 *
 * Speed slider: Min=0.1, Max=5.0, Whole Numbers=OFF
 * Weather slider: Min=0, Max=3, Whole Numbers=ON
 */

using UnityEngine;
using TMPro;
using Naval;

public class SimulationClock : MonoBehaviour
{
    [Header("References")]
    public BerthController berthController;
    public TMP_Text timeText;

    [Header("Speed")]
    [Tooltip("Ticks per second. 1 = real-time half-hours, 10 = fast")]
    public float ticksPerSecond = 2f;

    // Speed slider maps: left = slow (0.2 ticks/s), right = fast (20 ticks/s)
    private const float SPEED_MIN = 0.2f;
    private const float SPEED_MAX = 20f;

    void Start()
    {
        if (berthController == null)
        {
            berthController = FindObjectOfType<BerthController>();
            if (berthController == null)
            {
                Debug.LogError("[SimulationClock] BerthController not found.");
                return;
            }
        }

        // Subscribe to state updates
        berthController.OnStateUpdate += OnStateUpdate;

        // Apply initial speed
        ApplySpeed(ticksPerSecond);
    }

    void OnDestroy()
    {
        if (berthController != null)
            berthController.OnStateUpdate -= OnStateUpdate;
    }

    // ── Called after every step ───────────────────────────────────────────────

    private void OnStateUpdate(SimSnapshot snap)
    {
        if (timeText == null) return;

        // Convert simulation hours to day/hour/minute display
        float totalHours = snap.time_h;
        int days = (int)(totalHours / 24);
        int hours = (int)(totalHours % 24);
        int minutes = (int)((totalHours % 1) * 60);

        timeText.text = $"Day {days + 1}  {hours:D2}:{minutes:D2}";
    }

    // ── Speed slider ─────────────────────────────────────────────────────────
    // Wire slider OnValueChanged to this method.
    // Slider range: Min=0, Max=1 (normalized) — we map to SPEED_MIN..SPEED_MAX

    public void OnSpeedSliderChanged(float normalizedValue)
    {
        // Exponential mapping: slow end is very slow, fast end is very fast
        float speed = Mathf.Lerp(SPEED_MIN, SPEED_MAX, normalizedValue);
        ApplySpeed(speed);
    }

    private void ApplySpeed(float ticksPerSec)
    {
        ticksPerSecond = ticksPerSec;

        if (berthController == null) return;

        // Convert ticks/sec to interval in seconds
        float interval = 1f / Mathf.Max(ticksPerSec, 0.01f);
        berthController.playbackInterval = interval;

        // If already auto-stepping, restart with new interval
        berthController.StopAutoStep();
        berthController.StartAutoStep(interval);

        Debug.Log($"[SimulationClock] Speed: {ticksPerSec:F1} ticks/s  " +
                  $"(interval: {interval:F2}s = {ticksPerSec * 0.5f:F1} sim-hours/s)");
    }
}