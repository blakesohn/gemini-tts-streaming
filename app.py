import os
import sys
import datetime
import asyncio
import queue
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse, HTMLResponse
from google import genai
from google.genai import types
from google.cloud import texttospeech_v1beta1 as texttospeech
from pydantic import BaseModel
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize Client (Vertex AI) - Keeping for reference or fallback
project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
location = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
client = genai.Client(vertexai=True, project=project_id, location=location)

# Initialize Client (Cloud TTS - gRPC)
tts_client = texttospeech.TextToSpeechClient()

class TTSRequest(BaseModel):
    text: str
    voice_name: str = "Puck"

def get_tts_stream(text: str, voice_name: str):
    """Generates audio chunks from Gemini TTS."""
    config = types.GenerateContentConfig(
        speech_config=types.SpeechConfig(
            language_code="ko-KR",
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name
                )
            )
        )
    )
    
    request_start_time = datetime.datetime.now()
    is_first_chunk = True
    
    # Use streamed response
    response_stream = client.models.generate_content_stream(
        model="gemini-2.5-pro-tts",
        contents=text,
        config=config
    )

    for chunk in response_stream:
        if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
            for part in chunk.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    if is_first_chunk:
                        time_to_first = (datetime.datetime.now() - request_start_time).total_seconds()
                        print(f"\n[Server] Time to first audio: {time_to_first:.4f} seconds")
                        # Debug: Print first 20 bytes to ID format (RIFF=WAV, etc.)
                        header = part.inline_data.data[:20]
                        print(f"[Server] First chunk header: {header}")
                        is_first_chunk = False
                    
                    yield part.inline_data.data

    total_time = (datetime.datetime.now() - request_start_time).total_seconds()
    print(f"[Server] Time to completion: {total_time:.4f} seconds\n")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/tts/stream")
async def tts_stream(request: TTSRequest):
    return StreamingResponse(
        get_tts_stream(request.text, request.voice_name),
        media_type="audio/wav" # Stream as raw audio chunks (client can append to buffer)
    )

@app.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket):
    await websocket.accept()
    print("[WebSocket] Connected")

    # Queue for text chunks (Thread-safe, Sync)
    request_queue = queue.Queue()
    
    # Configure shared audio settings
    audio_config = texttospeech.StreamingAudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MULAW,
        sample_rate_hertz=24000
    )
    voice_config = texttospeech.VoiceSelectionParams(
        language_code="en-US", 
        name="en-US-Journey-F"
    )
    streaming_config = texttospeech.StreamingSynthesizeConfig(
        voice=voice_config,
        streaming_audio_config=audio_config
    )

    loop = asyncio.get_running_loop()

    def request_generator():
        # 1. First request: Config
        print("[gRPC] Starting new stream session")
        yield texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config)
        
        # 2. Subsequent requests: Text
        while True:
            try:
                # Wait briefly for new text. If none, close stream to prevent 5s timeout error.
                text = request_queue.get(timeout=2.0) 
                if text is None: 
                    return
                print(f"[gRPC] Sending text chunk: {text}")
                yield texttospeech.StreamingSynthesizeRequest(
                    input=texttospeech.StreamingSynthesisInput(text=text)
                )
            except queue.Empty:
                print("[gRPC] Stream idle, closing session locally.")
                return

    def run_grpc_session():
        """Runs a single gRPC streaming session until idle or error."""
        try:
            responses = tts_client.streaming_synthesize(request_generator())
            for response in responses:
                if response.audio_content:
                    # Send bytes to WebSocket
                    asyncio.run_coroutine_threadsafe(
                        websocket.send_bytes(response.audio_content), 
                        loop
                    )
        except Exception as e:
            print(f"[gRPC] Error in session: {e}")

    async def receive_text_from_ws():
        """Continuously receives text from WebSocket."""
        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text")
                if text:
                    request_queue.put(text)
                if data.get("eof"):
                    request_queue.put(None)
                    break
        except Exception:
            request_queue.put(None)

    async def manage_grpc_sessions():
        """Monitors queue and starts gRPC sessions when data is available."""
        while True:
            # Check if there is data pending in the queue
            if not request_queue.empty():
                # We have data, start a gRPC session
                await loop.run_in_executor(None, run_grpc_session)
            else:
                # Wait a bit before checking again to avoid busy loop
                await asyncio.sleep(0.1)
                
            # Exit condition? 
            # We rely on receive task cancellation or socket disconnect.

    # Run tasks
    receiver_task = asyncio.create_task(receive_text_from_ws())
    manager_task = asyncio.create_task(manage_grpc_sessions())
    
    try:
        # Wait for receiver to finish (e.g. connection closed)
        await receiver_task
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        manager_task.cancel()
        print("[WebSocket] Disconnected")

@app.websocket("/ws/llm-tts")
async def websocket_llm_tts(websocket: WebSocket):
    await websocket.accept()
    print("[WebSocket] Connected to LLM-TTS")

    # Shared Audio Config (Same as before)
    audio_config = texttospeech.StreamingAudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MULAW,
        sample_rate_hertz=24000
    )
    voice_config = texttospeech.VoiceSelectionParams(
        language_code="en-US", 
        name="en-US-Journey-F"
    )
    streaming_config = texttospeech.StreamingSynthesizeConfig(
        voice=voice_config,
        streaming_audio_config=audio_config
    )

    loop = asyncio.get_running_loop()

    try:
        # 1. Wait for user prompt
        data = await websocket.receive_json()
        prompt = data.get("text")
        print(f"[LLM-TTS] Received prompt: {prompt}")

        if not prompt:
            return
            
        # 0. Enforce length limit via prompt
        prompt += " (Please keep the response under 1000 characters)"

        def run_session():
            """Runs the synchronous LLM -> TTS chain."""
            try:
                # Use a specific client for Gemini 2.5 Flash as requested
                # Note: This assumes credentials (ADC) are sufficient or env vars are set.
                # If using Vertex AI, we might not need HttpOptions(api_version="v1") if the model is in the model garden,
                # but the user specifically asked for this configuration.
                # Use the existing import: from google.genai.types import HttpOptions (need to ensure it's imported)
                
                # Check imports - we need to make sure HttpOptions is available or import it here if needed.
                # Since we can't easily see imports at the top without reading again, we'll assume types is available 
                # as `from google.genai import types`. 
                # However, the user snippet had: `from google.genai.types import HttpOptions`
                
                # Let's verify imports first or just access via types if possible.
                # Checking `app.py` previously: `from google.genai import types`
                # So we can try `types.HttpOptions`.

                flash_client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location,
                    http_options=types.HttpOptions(api_version="v1")
                )

                # Generator that feeds TTS from LLM
                def tts_request_generator():
                    print("[LLM-TTS] Requesting Gemini stream...")
                    
                    llm_stream = flash_client.models.generate_content_stream(
                        model="gemini-2.5-flash",
                        contents=prompt,
                    )
                    
                    # Create an iterator to manually buffer the first chunk
                    llm_iterator = iter(llm_stream)
                    try:
                        # Wait for the first chunk BEFORE sending TTS config
                        # This prevents the TTS stream from timing out (5s limit) while waiting for LLM
                        first_chunk = next(llm_iterator)
                    except StopIteration:
                        print("[LLM-TTS] No content generated.")
                        return
                    except Exception as e:
                        print(f"[LLM-TTS] Error generating content: {e}")
                        return

                    # 1. Send TTS Config (now that we have data)
                    yield texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config)
                    
                    # 2. Send the first chunk
                    if first_chunk.text:
                        print(f"[LLM-TTS] Chunk: {first_chunk.text}")
                        # Send text to UI
                        asyncio.run_coroutine_threadsafe(
                            websocket.send_json({"type": "text", "content": first_chunk.text}),
                            loop
                        )
                        yield texttospeech.StreamingSynthesizeRequest(
                            input=texttospeech.StreamingSynthesisInput(text=first_chunk.text)
                        )

                    # 3. Stream the rest
                    for chunk in llm_iterator:
                        if chunk.text:
                            print(f"[LLM-TTS] Chunk: {chunk.text}")
                            # Send text to UI
                            asyncio.run_coroutine_threadsafe(
                                websocket.send_json({"type": "text", "content": chunk.text}),
                                loop
                            )
                            yield texttospeech.StreamingSynthesizeRequest(
                                input=texttospeech.StreamingSynthesisInput(text=chunk.text)
                            )
                
                # 3. Consume TTS Audio Stream
                tts_responses = tts_client.streaming_synthesize(tts_request_generator())
                
                for response in tts_responses:
                    if response.audio_content:
                        asyncio.run_coroutine_threadsafe(
                            websocket.send_bytes(response.audio_content),
                            loop
                        )
            except Exception as e:
                print(f"[LLM-TTS] Session Error: {e}")

        # Run the blocking session in a thread
        await loop.run_in_executor(None, run_session)

    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        await websocket.close()



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
