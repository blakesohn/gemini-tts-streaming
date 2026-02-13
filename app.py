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
import concurrent.futures
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize Client (Vertex AI) - Keeping for reference or fallback
project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
location = os.getenv("GOOGLE_CLOUD_REGION", "global")
client = genai.Client(vertexai=True, project=project_id, location=location)

# Initialize Client (Cloud TTS - gRPC)
tts_client = texttospeech.TextToSpeechClient()

# Initialize Client (Gemini Flash for Method 3)
flash_client = genai.Client(
    vertexai=True,
    project=project_id,
    location=location,
    http_options={'api_version': 'v1'}
)

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

    # Shared Audio Config - Using PCM (7) for gemini-2.5-pro-tts
    audio_config = texttospeech.StreamingAudioConfig(
        audio_encoding=texttospeech.AudioEncoding.PCM,
        sample_rate_hertz=24000
    )
    voice_config = texttospeech.VoiceSelectionParams(
        language_code="en-US", 
        name="Kore",
        model_name="gemini-2.5-pro-tts"
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
        prompt += " (Please keep the response under 500 characters)"

        def run_session():
            """Runs the LLM -> TTS chain using Pipelined Concurrency."""
            try:
                # Thread-safe queue for sentences
                # Items: str (sentence) or None (EOF)
                sentence_queue = queue.Queue()

                # Ordered Queue for Audio Futures
                # Items: (sentence_text, Future object) or None (EOF)
                audio_future_queue = queue.Queue()

                # --- Producer: LLM Reader ---
                def llm_producer():
                    print(f"[LLM-Producer] [{datetime.datetime.now()}] Requesting Gemini stream...")
                    try:
                        llm_stream = flash_client.models.generate_content_stream(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_modalities=["TEXT"]
                            )
                        )
                        
                        buffer = ""
                        for chunk in llm_stream:
                            text = chunk.text
                            if text:
                                # Send raw text to UI immediately for low-latency text stream
                                asyncio.run_coroutine_threadsafe(
                                    websocket.send_json({"type": "text", "content": text}),
                                    loop
                                )
                                
                                buffer += text
                                # Simple sentence splitting logic on delimiters
                                while True:
                                    # Find first delimiter
                                    match = None
                                    min_idx = -1
                                    
                                    for delimiter in ['.', '?', '!', '\n']:
                                        idx = buffer.find(delimiter)
                                        if idx != -1:
                                            if min_idx == -1 or idx < min_idx:
                                                min_idx = idx
                                    
                                    if min_idx != -1:
                                        # We have a sentence end
                                        sentence = buffer[:min_idx+1].strip()
                                        buffer = buffer[min_idx+1:]
                                        
                                        if sentence:
                                            print(f"[LLM-Producer] [{datetime.datetime.now()}] Queueing sentence ({len(sentence)} chars): {sentence[:30]}...")
                                            sentence_queue.put(sentence)
                                            
                                            # Notify UI of the full sentence unit
                                            asyncio.run_coroutine_threadsafe(
                                                websocket.send_json({
                                                    "type": "llm_sentence", 
                                                    "content": sentence,
                                                    "timestamp": datetime.datetime.now().isoformat()
                                                }),
                                                loop
                                            )
                                    else:
                                        break
                        
                        # End of stream, put remaining buffer if any
                        if buffer.strip():
                             print(f"[LLM-Producer] [{datetime.datetime.now()}] Queueing remaining: {buffer[:30]}...")
                             sentence_queue.put(buffer.strip())
                             
                        sentence_queue.put(None) # EOF for Scheduler
                        print(f"[LLM-Producer] [{datetime.datetime.now()}] Finished.")
                        
                    except Exception as e:
                        print(f"[LLM-Producer] Error: {e}")
                        sentence_queue.put(None)

                # --- Consumer 1: TTS Scheduler ---
                def tts_scheduler():
                    print("[TTS-Scheduler] Started.")
                    # Use a ThreadPoolExecutor to run TTS requests concurrently
                    # max_workers=5 allows up to 5 sentences to be processed in parallel
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        while True:
                            sentence = sentence_queue.get()
                            if sentence is None:
                                print("[TTS-Scheduler] Received EOF from LLM. Signaling Audio Sender.")
                                audio_future_queue.put(None) # EOF for Audio Sender
                                break
                            
                            print(f"[TTS-Scheduler] [{datetime.datetime.now()}] Scheduling: {sentence[:30]}...")

                            # Notify UI that processing started (Order preserved in scheduling)
                            asyncio.run_coroutine_threadsafe(
                                 websocket.send_json({
                                     "type": "audio_start", 
                                     "sentence": sentence[:30] + "...",
                                     "timestamp": datetime.datetime.now().isoformat()
                                 }),
                                 loop
                            )

                            # Define the task: Returns the response iterator
                            def fetch_tts_stream(text_to_speak):
                                def req_gen():
                                    yield texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config)
                                    yield texttospeech.StreamingSynthesizeRequest(
                                        input=texttospeech.StreamingSynthesisInput(text=text_to_speak)
                                    )
                                # This call starts the RPC and returns an iterator
                                return tts_client.streaming_synthesize(req_gen())

                            # Submit to executor
                            future = executor.submit(fetch_tts_stream, sentence)
                            
                            # Push future to ordered queue immediately to preserve playback order
                            audio_future_queue.put((sentence, future))

                # --- Consumer 2: Audio Sender ---
                def audio_sender():
                    print("[Audio-Sender] Started.")
                    while True:
                        item = audio_future_queue.get()
                        if item is None:
                            print("[Audio-Sender] Received EOF.")
                            break
                        
                        sentence, future = item
                        print(f"[Audio-Sender] [{datetime.datetime.now()}] Waiting for results of: {sentence[:30]}...")
                        
                        try:
                            # Wait for the specific future to complete (in order)
                            # Backpressure handled here: if retrieval is slow, queue fills up
                            response_iterator = future.result()
                            
                            is_first_audio = True
                            for response in response_iterator:
                                if response.audio_content:
                                    if is_first_audio:
                                        print(f"[Audio-Sender] [{datetime.datetime.now()}] First audio byte for: {sentence[:30]}...")
                                        is_first_audio = False
                                        
                                    asyncio.run_coroutine_threadsafe(
                                        websocket.send_bytes(response.audio_content),
                                        loop
                                    )
                        except Exception as e:
                            print(f"[Audio-Sender] Error playing '{sentence[:30]}...': {e}")
                
                # --- Encapsulate Thread Management ---
                import threading
                
                prod_thread = threading.Thread(target=llm_producer, daemon=True)
                sched_thread = threading.Thread(target=tts_scheduler, daemon=True)
                send_thread = threading.Thread(target=audio_sender, daemon=True)
                
                prod_thread.start()
                sched_thread.start()
                send_thread.start()
                
                prod_thread.join()
                sched_thread.join()
                send_thread.join()
                
                print(f"[LLM-TTS] [{datetime.datetime.now()}] Session completed")
                
            except Exception as e:
                print(f"[LLM-TTS] Session Error: {e}")

        # Run the blocking session manager in a thread (which spawns its own threads)
        await loop.run_in_executor(None, run_session)

    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        await websocket.close()



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
