# Gemini TTS Streaming Demo

This project demonstrates two different Text-to-Speech (TTS) streaming approaches using Google Cloud services.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Running the Server](#running-the-server)
- [Architecture Overview](#architecture-overview)
  - [Method 1: Unidirectional (Vertex AI)](#method-1-unidirectional-vertex-ai)
  - [Method 2: Bidirectional (Cloud TTS gRPC)](#method-2-bidirectional-cloud-tts-grpc)
- [Usage Guide](#usage-guide)

---

## Prerequisites

1. **Python 3.8+** installed
2. **Google Cloud Project** created
3. **Application Default Credentials (ADC)** configured
   ```bash
   gcloud auth application-default login
   ```
4. **Required APIs enabled**:
   - Vertex AI API
   - Cloud Text-to-Speech API

---

## Environment Setup

### Step 1: Configure Google Cloud Project

Copy the example environment file and set your project ID:

```bash
cp .env.example .env
```

Edit `.env` and update with your Google Cloud project details:

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_REGION=us-central1
```

> **Note**: The `.env` file is gitignored and will not be committed to version control.

### Step 2: Install and Run

#### Option 1: Automated Setup (Recommended)

The `run_web.sh` script automatically creates the virtual environment and installs dependencies.

```bash
chmod +x run_web.sh
./run_web.sh
```


### Option 2: Manual Setup

#### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env and set your GOOGLE_CLOUD_PROJECT
```

#### 2. Create Virtual Environment

```bash
python3 -m venv venv
```

#### 3. Activate Virtual Environment

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```cmd
venv\Scripts\activate
```

#### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

**requirements.txt contents:**
- `google-genai`: Vertex AI Gemini SDK
- `google-cloud-texttospeech`: Cloud TTS gRPC client
- `fastapi`: Web framework
- `uvicorn`: ASGI server
- `jinja2`: HTML template engine
- `python-dotenv`: Environment variable management

---

## Running the Server

### Automated Run

```bash
./run_web.sh
```

### Manual Run

```bash
# After activating virtual environment
uvicorn app:app --reload --host 0.0.0.0 --port 8001
```

Once the server starts, open your browser and navigate to:
```
http://127.0.0.1:8001
```

---

## Architecture Overview

### Method 1: Unidirectional (Vertex AI)

**Unidirectional Streaming**: User submits text to the server, which returns an audio stream as the response.

#### Components

- **SDK**: `google-genai` (Vertex AI)
- **Model**: `gemini-2.5-pro-tts`
- **Voice Configuration**:
  - Language: `ko-KR` (Korean)
  - Voice: `Puck` (prebuilt voice)
- **Protocol**: HTTP POST request → Server-Sent Events (SSE) streaming

#### Flow

```
[Browser] --POST /tts/stream--> [FastAPI Server] --generate_content_stream--> [Vertex AI Gemini]
[Browser] <--Audio Chunks------ [FastAPI Server] <--Audio Data-------------- [Vertex AI Gemini]
```

1. User enters text and clicks "Speak" button
2. Browser sends POST request to `/tts/stream` endpoint
3. Server calls Vertex AI's `gemini-2.5-pro-tts` model
4. Model streams generated audio chunks in response
5. Browser plays chunks in real-time using Web Audio API

#### Features

- ✅ **Fast Time-to-First-Audio (TTFA)**
- ✅ **Simple implementation** (unidirectional HTTP)
- ✅ **WAV format** output
- ❌ No persistent connection (one request per session)

---

### Method 2: Bidirectional (Cloud TTS gRPC)

**Bidirectional Streaming**: Client and server maintain a WebSocket connection, while the server communicates bidirectionally with Cloud TTS via gRPC.

#### Components

- **SDK**: `google-cloud-texttospeech` (gRPC)
- **API**: Cloud Text-to-Speech v1beta1
- **Voice Configuration**:
  - Language: `en-US`
  - Voice: `en-US-Journey-F`
  - Audio Encoding: `MULAW` (8-bit compressed)
  - Sample Rate: 24,000 Hz
- **Protocol**: WebSocket (Client ↔ Server) + gRPC Streaming (Server ↔ Cloud)

#### Flow

```
[Browser] <--WebSocket--> [FastAPI Server] <--gRPC Bidirectional--> [Cloud TTS]
   ↓                           ↓                                          ↓
Input Text Stream         Queue Management                       Audio Synthesis
Output Audio Stream       Session Control                        Streaming Response
```

**Detailed Steps:**

1. **Connection Establishment**:
   - Browser connects to `/ws/tts` WebSocket endpoint
   - Server prepares gRPC session

2. **Input Streaming** (Text → Server):
   - User types text; automatically sent after 800ms pause (debounce)
   - WebSocket sends JSON message: `{ "text": "..." }`
   - Server stores text in queue

3. **gRPC Session**:
   - Server retrieves text from queue and creates gRPC stream
   - First request: `StreamingSynthesizeConfig` (voice settings)
   - Subsequent requests: `StreamingSynthesisInput` (text)

4. **Output Streaming** (Audio ← Server):
   - Cloud TTS returns MULAW-encoded audio chunks
   - Server forwards binary data via WebSocket
   - Browser decodes μ-law to Float32 and plays audio

5. **Session Management**:
   - gRPC stream auto-closes after 2 seconds of inactivity (idle timeout)
   - New session starts automatically when new input arrives

#### Features

- ✅ **Bidirectional real-time communication** (WebSocket + gRPC)
- ✅ **Persistent connection** (multiple text chunks can be sent)
- ✅ **Visual monitoring**:
  - `INPUT STREAM`: Shows sent text chunks
  - `OUTPUT STREAM`: Visualizes received audio packet sizes
- ✅ **Automatic session management** (idle timeout, reconnection)
- ⚠️ Potential audio quality reduction due to MULAW encoding

#### UI Controls

- **Connect**: Start WebSocket connection
- **Stop**: Close connection and reset UI
- **Streaming Monitor**: 
  - Left panel: Log of sent text
  - Right panel: Bar graph of received audio bytes

---

## Usage Guide

### Testing Method 1

1. Enter Korean text in the "Method 1: Unidirectional (Vertex AI)" text area
2. Click "Speak" button
3. Audio streams and plays immediately
4. Check Time-to-First-Audio and completion time in status message

### Testing Method 2

1. Click "Connect" in "Method 2: Bidirectional (Cloud TTS gRPC)" section
2. Type English sentence in text area
3. Text auto-sends after 800ms pause in typing
4. **INPUT STREAM** panel shows sent text
5. **OUTPUT STREAM** panel visualizes audio data
6. Audio plays automatically
7. Additional text can be entered (connection persists)
8. Click "Stop" to close connection

---

## Project Structure

```
gemini-tts/
├── app.py                  # FastAPI application (Methods 1 & 2)
├── main.py                 # CLI testing tool
├── requirements.txt        # Python dependencies
├── run_web.sh             # Automated run script
├── templates/
│   └── index.html         # Web UI (includes Streaming Monitor)
└── venv/                  # Virtual environment (auto-generated)
```

---

## Troubleshooting

### 1. ADC Authentication Error

```bash
gcloud auth application-default login
```

### 2. API Activation Required

Enable in Google Cloud Console:
- Vertex AI API
- Cloud Text-to-Speech API

### 3. WebSocket Connection Failure

- Verify server is running properly
- Check browser console for error messages
- Verify firewall settings (port 8001)

### 4. Audio Not Playing

- Check browser autoplay policy
- Attempt playback after user interaction (button click)

---

## License

MIT License
