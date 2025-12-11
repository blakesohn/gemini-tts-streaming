from google.genai import types
import inspect

try:
    print("SpeechConfig annotations:", types.SpeechConfig.__annotations__)
except Exception as e:
    print("Error:", e)
