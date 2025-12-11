import os
from google.cloud import texttospeech_v1beta1 as texttospeech

client = texttospeech.TextToSpeechClient()

def test_streaming():
    audio_config = texttospeech.StreamingAudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        # sample_rate_hertz=24000
    )
    voice_config = texttospeech.VoiceSelectionParams(
        language_code="en-US", 
        name="en-US-Journey-F"
    )
    streaming_config = texttospeech.StreamingSynthesizeConfig(
        voice=voice_config,
        streaming_audio_config=audio_config
    )

    def request_generator():
        yield texttospeech.StreamingSynthesizeRequest(streaming_config=streaming_config)
        yield texttospeech.StreamingSynthesizeRequest(
            input=texttospeech.StreamingSynthesisInput(text="Hello world")
        )

    try:
        responses = client.streaming_synthesize(request_generator())
        for response in responses:
            print("Received bytes:", len(response.audio_content))
            break
        print("Success!")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_streaming()
