using System.Collections.Generic;
using UnityEngine;

public class PortVisualizer : MonoBehaviour {
    [Header("Pier References")]
    public Transform[] pierTransforms;  // 8 piers in order P1-P8
    public Transform[][] slotPositions; // pierTransforms[i][j] = slot j of pier i
    
    [Header("Prefabs")]
    public GameObject shipPrefab;
    
    Dictionary<string, ShipView> shipsById = new();
    
    public void ApplyState(StateMessage state) {
        // Update ships
        UpdateShips(state.ships);
        
        // Update UI (later)
        UpdateGlobalUI(state);
    }
    
    void UpdateShips(ShipState[] shipStates) {
        HashSet<string> currentIds = new();
        
        foreach (var shipState in shipStates) {
            currentIds.Add(shipState.id);
            
            if (!shipsById.TryGetValue(shipState.id, out ShipView shipView)) {
                // Spawn new ship
                GameObject shipObj = Instantiate(shipPrefab, Vector3.zero, Quaternion.identity);
                shipView = shipObj.GetComponent<ShipView>();
                shipsById[shipState.id] = shipView;
            }
            
            // Position ship
            PositionShip(shipView, shipState);
        }
        
        // Destroy departed ships
        List<string> toRemove = new();
        foreach (var kvp in shipsById) {
            if (!currentIds.Contains(kvp.Key)) {
                toRemove.Add(kvp.Key);
            }
        }
        foreach (string id in toRemove) {
            Destroy(shipsById[id].gameObject);
            shipsById.Remove(id);
        }
    }
    
    void PositionShip(ShipView shipView, ShipState state) {
    shipView.SetState(state);
    
    if (!string.IsNullOrEmpty(state.pier) && state.layer >= 0) {
        // AT_BERTH: move to pier slot
        int pierIdx = int.Parse(state.pier.Substring(1)) - 1;  // P1→0, P2→1...
        int layerIdx = state.layer;
        
        if (pierIdx < pierTransforms.Length && layerIdx < slotPositions[pierIdx].Length) {
            shipView.transform.position = slotPositions[pierIdx][layerIdx].position;
            shipView.transform.rotation = Quaternion.identity;
        }
    } else {
        // WAITING/FUTURE: float above center
        shipView.transform.position = new Vector3(
            Random.Range(-20f, 20f), 
            5f + shipsById.Count * 0.5f, 
            Random.Range(-5f, 5f)
        );
    }
}

    void UpdateGlobalUI(StateMessage state) {
        // Weather, night, metrics UI here (later)
    }
}