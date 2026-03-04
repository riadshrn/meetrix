import sounddevice as sd
import numpy as np

devices = sd.query_devices()
print("=== Périphériques d'entrée ===")
for i, d in enumerate(devices):
    if d["max_input_channels"] > 0:
        print(f"{i}: {d['name']}")

idx = int(input("\nEntrez l'index à tester : "))

def callback(indata, frames, time, status):
    vol = np.linalg.norm(indata) * 10
    bar = "#" * int(vol)
    print(f"\r{bar:<50} {vol:.1f}", end="", flush=True)

print("Parlez... (Ctrl+C pour arrêter)\n")
with sd.InputStream(device=idx, channels=1, callback=callback):
    input()
