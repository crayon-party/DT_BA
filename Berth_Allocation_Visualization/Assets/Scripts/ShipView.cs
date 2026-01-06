using UnityEngine;

public class ShipView : MonoBehaviour
{
    [Header("Ship Info")]
    public string shipId;
    public string shipType;

    [Header("Visual")]
    public Renderer shipRenderer;
    public Transform shipModel;

    Material defaultMat;

    void Awake()
    {
        if (shipRenderer != null) defaultMat = shipRenderer.material;
    }

    public void SetState(ShipState state)
    {
        shipId = state.id;
        shipType = state.type;

        // Color by type
        Color color = shipType switch
        {
            "P" => Color.cyan,
            "F" => Color.yellow,
            "L" => Color.magenta,
            "K" => Color.red,
            _ => Color.white
        };
        if (shipRenderer != null) shipRenderer.material.color = color;

        // Scale by type
        float scale = shipType switch
        {
            "P" => 8.0f,
            "F" => 12.0f,
            "L" => 15.0f,
            "K" => 18.0f,
            _ => 10.0f
        };
        if (shipModel != null) shipModel.localScale = Vector3.one * scale;

        // Status visual
        UpdateStatusVisual(state.status);
    }

    void UpdateStatusVisual(string status)
    {
        switch (status)
        {
            case "FUTURE":
                transform.position += Vector3.up * 2;  // float high
                if (shipRenderer != null) shipRenderer.material.color *= 0.5f;
                break;
            case "WAITING":
                transform.Rotate(0, Time.deltaTime * 30, 0);
                break;
            case "AT_BERTH":
                transform.rotation = Quaternion.identity;
                break;
            case "READY_DEPART":
                if (shipRenderer != null) shipRenderer.material.color = Color.green;
                break;
        }
    }
}