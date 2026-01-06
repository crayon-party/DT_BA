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
    
    void Awake() {
        defaultMat = shipRenderer.material;
    }
    
    public void SetState(ShipState state) {
        shipId = state.id;
        shipType = state.type;
        
        // Color by type
        Color color = shipType switch {
            "P" => Color.cyan,      // Small patrol
            "F" => Color.yellow,    // Frigate
            "L" => Color.magenta,   // Large
            "K" => Color.red,       // Largest
            _ => Color.white
        };
        shipRenderer.material.color = color;
        
        // Scale by type (optional)
        float scale = shipType switch {
            "P" => 0.8f,
            "F" => 1.0f,
            "L" => 1.3f,
            "K" => 1.6f,
            _ => 1.0f
        };
        shipModel.localScale = Vector3.one * scale;
        
        // Status visual
        UpdateStatusVisual(state.status);
    }
    
    void UpdateStatusVisual(string status) {
        switch (status) {
            case "FUTURE":
                transform.position += Vector3.up * 2;  // Float high
                shipRenderer.material.color *= 0.5f;   // Dim
                break;
            case "WAITING":
                transform.Rotate(0, Time.deltaTime * 30, 0);  // Rotate slowly
                break;
            case "AT_BERTH":
                transform.rotation = Quaternion.identity;
                break;
            case "READY_DEPART":
                shipRenderer.material.color = Color.green;  // Ready to go
                break;
        }
    }
}
