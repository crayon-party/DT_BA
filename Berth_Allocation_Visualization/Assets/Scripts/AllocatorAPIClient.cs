//using UnityEngine;
//using UnityEngine.Networking;
//using System.Collections;
//using System;

//public class AllocatorAPIClient : MonoBehaviour
//{
//    [Serializable] public class SimState { /* matches snapshot_to_dict() */ }

//    public string apiUrl = "http://localhost:8000";
//    private SimState currentState;

//    void Start()
//    {
//        StartCoroutine(InitScenario());
//    }

//    //IEnumerator InitScenario()
//    {
//        // Send scenario to Python
//       // yield return SendPost("/init_scenario", scenarioJson);
//    }

//    public void OnEnvironmentChange()
//    {
//        // Unity UI/slider changed weather, time accel, etc.
//       // StartCoroutine(SendPost("/init_scenario", updatedState));
//    }

//   // IEnumerator StepSimulation()
//    {
//       // var response = SendPost("/step_forward", sessionId);
//        currentState = JsonUtility.FromJson<SimState>(response);
//        UpdateVisualization();
//        //yield return new WaitForSeconds(timeStep);
//    }

//   / void UpdateVisualization()
//    {
//        // Clear scene, spawn vessels/tugs per currentState.ships, tugs
//        // Animate movements, update Gantt, metrics dashboard
//    }
//}
