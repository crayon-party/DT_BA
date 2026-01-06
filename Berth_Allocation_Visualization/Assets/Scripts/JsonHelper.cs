using System;
using UnityEngine;

public static class JsonHelper
{
    public static T[] FromJson<T>(string json)
    {
        // If JSON starts with '[', wrap it
        if (json.TrimStart().StartsWith("["))
        {
            json = "{ \"Items\": " + json + " }";
        }

        Wrapper<T> wrapper = JsonUtility.FromJson<Wrapper<T>>(json);
        return wrapper.Items;
    }

    [Serializable]
    private class Wrapper<T>
    {
        public T[] Items;
    }
}