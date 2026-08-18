import json
import logging
import asyncio
from dotenv import load_dotenv
load_dotenv()

from google.cloud import storage
from google.genai import types
from google.adk import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from app.agent import root_agent

# Configure clean visual logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("batch_runner")

async def process_call_transcript(runner: Runner, blob_name: str, file_content: str):
    """
    Feeds a single call log record to the ADK Orchestrator runner,
    monitors and logs the execution stream events, and catches exception blocks.
    """
    logger.info(f"🚀 [Ingest Process] Starting workflow for transcript file: '{blob_name}'...")
    try:
        call_data = json.loads(file_content)
        
        # Enclose call details into the prompt payload trigger
        payload_str = json.dumps({
            "metadata": call_data.get("metadata", {}),
            "transcript": call_data.get("transcript", [])
        })
        prompt_trigger = f"Process this call log record:\n{payload_str}"
        
        # Format standardized google-genai Content structure for ADK input
        user_prompt = types.Content(
            role="user",
            parts=[types.Part(text=prompt_trigger)]
        )
        
        # Execute the ADK pipeline stream using unique session names per file
        result_stream = runner.run_async(
            user_id="poc_operator",
            session_id=blob_name, # Session isolation per transcript
            new_message=user_prompt
        )
        
        # Monitor and stream logs in stdout
        async for event in result_stream:
            if event.content and event.content.parts:
                text_part = "".join([p.text for p in event.content.parts if p.text])
                if text_part.strip():
                    logger.info(f" └─ [{event.author}]: {text_part.strip()}")
                    
        logger.info(f"✅ [Ingest Success] Successfully analyzed and warehoused: '{blob_name}'")
    except Exception as e:
        logger.error(f"❌ [Ingest Error] Ingestion failed for file '{blob_name}': {str(e)}")

async def run_batch_poc():
    """
    Scans the target 'genai-demos_synthetic_call_transcripts' bucket,
    initializes the ADK in-memory runner context, and loops over target logs.
    """
    bucket_name = "genai-demos_synthetic_call_transcripts"
    storage_client = storage.Client()
    
    logger.info(f"📂 Scanning Google Cloud Storage bucket '{bucket_name}'...")
    try:
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs())
    except Exception as e:
        logger.error(f"❌ Failed to connect to GCS bucket: {str(e)}")
        logger.error("💡 Please verify your gcloud authentication and check network access.")
        return
        
    logger.info(f"🎯 Target transcripts found: {len(blobs)}. Initializing AI reasoning engines...")
    
    # Instantiate standalone in-memory session service and runner backend
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="transcript_analyzer",
        agent=root_agent,
        session_service=session_service,
        auto_create_session=True
    )
    
    logger.info("Commencing PoC execution cycle (sequential processing to respect Vertex rate boundaries)...")
    
    for i, blob in enumerate(blobs):
        logger.info(f"\n========================================================")
        logger.info(f"👉 [Transcript {i+1} / {len(blobs)}] processing file: '{blob.name}'")
        logger.info(f"========================================================")
        try:
            file_content = blob.download_as_text()
            await process_call_transcript(runner, blob.name, file_content)
        except Exception as e:
            logger.error(f"❌ Downloading failed for '{blob.name}': {str(e)}")
            
    logger.info("\n🏁 Ingestion batch successfully concluded! All analyzed data pushed to BigQuery call_analyzer.")

if __name__ == "__main__":
    asyncio.run(run_batch_poc())
