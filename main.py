import os
import queue
import sys
import threading
import pyaudio
from google import genai
from google.genai import types

# Audio configuration
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000  # Gemini TTS output sample rate
CHUNK = 1024

def get_client():
    """Initializes the Gemini client."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    
    if not project_id:
        print("Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
        sys.exit(1)

    return genai.Client(vertexai=True, project=project_id, location=location)

def play_audio_worker(audio_queue, stream, stop_event):
    """Continuously reads from the queue and writes to the stream."""
    while not stop_event.is_set() or not audio_queue.empty():
        try:
            # Wait for data with a timeout to check stop_event
            data = audio_queue.get(timeout=0.1)
            if data:
                stream.write(data)
        except queue.Empty:
            continue
        except OSError as e:
            print(f"\n[Audio Error] Error writing to stream: {e}")
            break

def main():
    client = get_client()
    
    print("Gemini TTS Streaming App")
    print("------------------------")
    
    # Initialize PyAudio once
    p = pyaudio.PyAudio()
    
    try:
        # Open stream once if possible, or open/close per request. 
        # Keeping it open is often more stable for repeated use.
        stream = p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        output=True)
        
        print("Audio output initialized.")
        print("Enter text to synthesize (or 'q' to quit):")

        while True:
            text = input("\nText: ").strip()
            if text.lower() == 'q':
                break
            if not text:
                continue

            print("Streaming response...", end="", flush=True)

            config = types.GenerateContentConfig(
                speech_config=types.SpeechConfig(
                    language_code="ko-KR",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Puck"
                        )
                    )
                )
            )

            audio_queue = queue.Queue()
            stop_event = threading.Event()
            
            # Start player thread for this turn
            player_thread = threading.Thread(target=play_audio_worker, args=(audio_queue, stream, stop_event))
            player_thread.start()

            try:
                model_name = "gemini-2.5-pro-tts"
                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=text,
                    config=config
                )

                for chunk in response_stream:
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for part in chunk.candidates[0].content.parts:
                            if part.inline_data and part.inline_data.data:
                                 audio_queue.put(part.inline_data.data)
                                 print(".", end="", flush=True)

            except Exception as e:
                print(f"\nError during synthesis: {e}")
            finally:
                # Wait for audio to finish playing
                stop_event.set()
                player_thread.join()
                print("\nDone.")

    except OSError as e:
        print(f"\n[Critical Audio Error] Could not open audio stream: {e}")
        print("Ensure your audio device is available and accessible.")
    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        if 'stream' in locals() and stream.is_active():
            stream.stop_stream()
            stream.close()
        p.terminate()
        print("\nExiting.")

if __name__ == "__main__":
    main()
