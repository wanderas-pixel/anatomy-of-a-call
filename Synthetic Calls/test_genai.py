from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List

class TranscriptTurn(BaseModel):
    timestamp: str = Field(description="Relative timestamp in 'MM:SS' format from start of call")
    speaker: str = Field(description="Must be either 'Agent' or 'User'")
    text: str = Field(description="The word-for-word spoken utterance")

class CallTranscript(BaseModel):
    turns: List[TranscriptTurn] = Field(description="The sequential turns of the telephone call")

try:
    client = genai.Client(
        vertexai=True,
        project="genai-demos-391416",
        location="us-central1"
    )

    print("Testing Cymbal Telecom content generation...")
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents='Generate a very short 3-turn phone call with relative timestamps starting at 00:00 about a payments issue. The agent MUST explicitly greet the customer on behalf of Cymbal Telecom, which is the only telecom provider brand name allowed.',
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CallTranscript,
            temperature=0.7
        )
    )
    print("\nSUCCESS! Response from gemini-2.5-pro:")
    print(response.text.strip())
except Exception as e:
    print("\nERROR occurred:")
    print(e)
