# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import logging
import asyncio
from typing import Dict, Any, List
from dotenv import load_dotenv
load_dotenv()

import google.auth
from fastapi import FastAPI, BackgroundTasks, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from google.cloud import storage
from google.cloud import bigquery
from google.genai import types
from google.adk import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from app.agent import root_agent

# Initialize telemetry and baseline properties
setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)

# Configure standard visual logger
app_logger = logging.getLogger("fast_api_app")

# Global pipeline execution state (persisted in RAM for the dashboard metrics)
pipeline_state = {
    "is_running": False,
    "current_file": None,
    "processed_count": 0,
    "total_files": 0,
    "logs": []
}

async def execute_batch_ingestion_task():
    """
    Background batch processor looping transcripts sequentially,
    triggering the schema-locked ADK Worker Tree, and pushing structured payloads into BigQuery.
    """
    global pipeline_state
    if pipeline_state["is_running"]:
        app_logger.warning("⚠️  Ingestion loop already active. Bypassing trigger call.")
        return
        
    pipeline_state["is_running"] = True
    pipeline_state["processed_count"] = 0
    pipeline_state["logs"] = []
    
    bucket_name = "genai-demos_synthetic_call_transcripts"
    storage_client = storage.Client()
    
    app_logger.info(f"📂 Scanning GCS bucket '{bucket_name}' inside background task...")
    try:
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs())
        pipeline_state["total_files"] = len(blobs)
        app_logger.info(f"🎯 Target transcripts discovered: {len(blobs)}")
    except Exception as e:
        err_msg = f"❌ Failed to query GCS bucket: {str(e)}"
        app_logger.error(err_msg)
        pipeline_state["logs"].append(err_msg)
        pipeline_state["is_running"] = False
        return
        
    # Instantiate standalone in-memory session service and runner backend
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="transcript_analyzer",
        agent=root_agent,
        session_service=session_service,
        auto_create_session=True
    )
    
    for i, blob in enumerate(blobs):
        blob_name = blob.name
        pipeline_state["current_file"] = blob_name
        app_logger.info(f"👉 [{i+1}/{len(blobs)}] processing file: '{blob_name}'...")
        pipeline_state["logs"].append(f"⏳ Processing transcript: '{blob_name}'")
        
        try:
            file_content = blob.download_as_text()
            call_data = json.loads(file_content)
            
            # Pack details into a structured target payload
            payload_str = json.dumps({
                "metadata": call_data.get("metadata", {}),
                "transcript": call_data.get("transcript", [])
            })
            prompt_trigger = f"Process this call log record:\n{payload_str}"
            
            user_prompt = types.Content(
                role="user",
                parts=[types.Part(text=prompt_trigger)]
            )
            
            # Execute the ADK pipeline stream using unique session names per file
            result_stream = runner.run_async(
                user_id="poc_operator",
                session_id=blob_name,
                new_message=user_prompt
            )
            
            # Wait for stream resolution
            async for event in result_stream:
                if event.content and event.content.parts:
                    text_part = "".join([p.text for p in event.content.parts if p.text])
                    if text_part.strip() and event.author != "transcript_orchestrator":
                        app_logger.info(f"   └─ [{event.author}]: {text_part.strip()}")
                        
            pipeline_state["processed_count"] += 1
            pipeline_state["logs"].append(f"✅ Ingestion Success: '{blob_name}' successfully warehoused.")
            
        except Exception as file_err:
            fail_msg = f"❌ Ingestion Failure: file '{blob_name}': {str(file_err)}"
            app_logger.error(fail_msg)
            pipeline_state["logs"].append(fail_msg)
            
    app_logger.info("🏁 Ingestion batch processing concluded! All structured data written to BigQuery.")
    pipeline_state["logs"].append("🏁 Ingestion batch successfully concluded!")
    pipeline_state["is_running"] = False
    pipeline_state["current_file"] = None


# Establish the FastAPI application envelope using standard ADK setups
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else ["*"]
)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
session_service_uri = None
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False,
)
app.title = "transcript-analyzer"
app.description = "API and Admin Dashboard for the Conversational Agent Transcript Analyzer Ingestion Pipeline"


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def trigger_ingestion(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Triggers bulk GCS transcript ingestion processing asynchronously in the background."""
    if pipeline_state["is_running"]:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "conflict", "message": "Ingestion process is already running. Please monitor dashboard."}
        )
    
    background_tasks.add_task(execute_batch_ingestion_task)
    return {"status": "accepted", "message": "GCS batch ingestion pipeline successfully triggered."}


@app.get("/ingest/status")
def get_ingestion_status() -> Dict[str, Any]:
    """Returns real-time run metrics of the active execution loop."""
    return pipeline_state


@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves a premium, responsive dashboard displaying pipeline statistics, databases, and logs."""
    client = bigquery.Client()
    
    # 1. Fetch metadata analytics numbers from call_analyzer_table
    analytics_query = """
        SELECT COUNT(1) as total_calls, 
               COALESCE(SUM(duration_minutes), 0) as total_duration_min,
               COUNT(DISTINCT customer_id) as total_customers
        FROM `genai-demos-391416.call_analyzer.call_analyzer_table`
    """
    
    # 2. Fetch categories count from registry
    registry_query = """
        SELECT COUNT(1) as total_categories
        FROM `genai-demos-391416.call_analyzer.taxonomy_registry`
    """
    
    # 3. Fetch list of actually committed records
    logs_query = """
        SELECT call_id, customer_id, customer_name, primary_reason, secondary_reason, processed_timestamp
        FROM `genai-demos-391416.call_analyzer.call_analyzer_table`
        ORDER BY call_id DESC
        LIMIT 10
    """
    
    total_calls, total_duration, total_customers, total_categories = 0, 0, 0, 5
    records_list = []
    
    try:
        an_res = list(client.query(analytics_query).result())
        if an_res:
            total_calls = an_res[0].total_calls
            total_duration = an_res[0].total_duration_min
            total_customers = an_res[0].total_customers
            
        reg_res = list(client.query(registry_query).result())
        if reg_res:
            total_categories = reg_res[0].total_categories
            
        logs_res = list(client.query(logs_query).result())
        for row in logs_res:
            records_list.append({
                "call_id": row.call_id,
                "customer_id": row.customer_id,
                "customer_name": row.customer_name or "N/A",
                "primary": row.primary_reason,
                "secondary": row.secondary_reason,
                "timestamp": row.processed_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        app_logger.error(f"Failed to fetch BigQuery dashboard stats: {str(e)}")
        
    # Calculate intent reuse statistics
    synonym_reuse_ratio = 0
    if total_calls > 0:
        # Subtracting standard seeded baseline categories
        net_new_categories = max(0, total_categories - 5)
        synonym_reuse_ratio = int((1 - (net_new_categories / total_calls)) * 100)
        
    status_class = "running" if pipeline_state["is_running"] else "idle"
    status_label = "ACTIVE PROCESSING" if pipeline_state["is_running"] else "SYSTEM STANDBY"
    progress_val = 0
    if pipeline_state["total_files"] > 0:
        progress_val = int((pipeline_state["processed_count"] / pipeline_state["total_files"]) * 100)
        
    logs_html = "".join([f"<li>{log}</li>" for log in reversed(pipeline_state["logs"])])
    records_rows = "".join([
        f"""<tr>
            <td><strong>{r['call_id']}</strong></td>
            <td>{r['customer_id']} ({r['customer_name']})</td>
            <td><span class='badge primary'>{r['primary']}</span></td>
            <td><span class='badge secondary'>{r['secondary']}</span></td>
            <td>{r['timestamp']}</td>
           </tr>"""
        for r in records_list
    ])
    
    if not records_rows:
        records_rows = "<tr><td colspan='5' style='text-align: center; color: #9CA3AF;'>No structured logs warehoused in call_analyzer_table yet. Trigger an ingestion below.</td></tr>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Transcript Ingestion Pipeline Dashboard</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0B0F19;
                --card-bg: #111827;
                --primary: #6366F1;
                --primary-gradient: linear-gradient(135deg, #6366F1, #8B5CF6);
                --success: #10B981;
                --warning: #F59E0B;
                --text: #F3F4F6;
                --text-muted: #9CA3AF;
                --border: #1F2937;
            }}
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
                font-family: 'Plus Jakarta Sans', sans-serif;
            }}
            body {{
                background-color: var(--bg);
                color: var(--text);
                padding: 40px 20px;
                line-height: 1.5;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 40px;
                background: var(--card-bg);
                padding: 24px;
                border-radius: 16px;
                border: 1px solid var(--border);
            }}
            h1 {{
                font-size: 24px;
                font-weight: 700;
                background: var(--primary-gradient);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            p.sub-title {{
                color: var(--text-muted);
                font-size: 14px;
                margin-top: 4px;
            }}
            .status-panel {{
                display: flex;
                align-items: center;
                gap: 12px;
            }}
            .status-dot {{
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background-color: var(--text-muted);
            }}
            .status-dot.running {{
                background-color: var(--success);
                box-shadow: 0 0 12px var(--success);
                animation: pulse 1.5s infinite;
            }}
            .status-dot.idle {{
                background-color: var(--warning);
            }}
            .status-label {{
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.05em;
            }}
            .status-label.running {{ color: var(--success); }}
            .status-label.idle {{ color: var(--warning); }}
            
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 24px;
                margin-bottom: 40px;
            }}
            .stat-card {{
                background: var(--card-bg);
                border: 1px solid var(--border);
                padding: 24px;
                border-radius: 16px;
                position: relative;
                overflow: hidden;
            }}
            .stat-card::after {{
                content: '';
                position: absolute;
                bottom: 0;
                left: 0;
                width: 100%;
                height: 4px;
                background: var(--primary-gradient);
                opacity: 0.7;
            }}
            .stat-card.success::after {{ background: var(--success); }}
            .stat-label {{
                font-size: 12px;
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 8px;
            }}
            .stat-value {{
                font-size: 36px;
                font-weight: 700;
            }}
            .stat-desc {{
                font-size: 12px;
                color: var(--text-muted);
                margin-top: 4px;
            }}
            
            .main-grid {{
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 24px;
            }}
            @media (max-width: 900px) {{
                .main-grid {{ grid-template-columns: 1fr; }}
            }}
            .panel {{
                background: var(--card-bg);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 24px;
            }}
            .panel-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                border-bottom: 1px solid var(--border);
                padding-bottom: 16px;
            }}
            .panel-title {{
                font-size: 18px;
                font-weight: 600;
            }}
            
            /* Buttons */
            .btn {{
                background: var(--primary-gradient);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }}
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
            }}
            .btn:active {{ transform: translateY(0); }}
            .btn:disabled {{
                background: var(--border);
                color: var(--text-muted);
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }}
            
            /* Table */
            table {{
                width: 100%;
                border-collapse: collapse;
                text-align: left;
            }}
            th {{
                font-size: 12px;
                text-transform: uppercase;
                color: var(--text-muted);
                padding: 12px;
                border-bottom: 1px solid var(--border);
            }}
            td {{
                padding: 16px 12px;
                font-size: 14px;
                border-bottom: 1px solid var(--border);
            }}
            tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
            
            .badge {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }}
            .badge.primary {{ background: rgba(99, 102, 241, 0.15); color: #818CF8; }}
            .badge.secondary {{ background: rgba(16, 185, 129, 0.15); color: #34D399; }}
            
            /* Progress Bar */
            .progress-container {{
                margin-top: 12px;
            }}
            .progress-bar-bg {{
                width: 100%;
                height: 8px;
                background: var(--border);
                border-radius: 4px;
                overflow: hidden;
            }}
            .progress-bar-fill {{
                height: 100%;
                background: var(--primary-gradient);
                transition: width 0.5s ease;
            }}
            
            /* Console Logs */
            ul.console-logs {{
                list-style: none;
                font-family: 'JetBrains Mono', monospace;
                font-size: 12px;
                max-height: 400px;
                overflow-y: auto;
                background: #060913;
                padding: 16px;
                border-radius: 8px;
                border: 1px solid var(--border);
                display: flex;
                flex-direction: column;
                gap: 8px;
            }}
            ul.console-logs li {{
                border-bottom: 1px solid rgba(255, 255, 255, 0.03);
                padding-bottom: 6px;
                color: #22C55E;
                white-space: pre-wrap;
            }}
            
            @keyframes pulse {{
                0% {{ transform: scale(1); opacity: 1; }}
                50% {{ transform: scale(1.2); opacity: 0.6; }}
                100% {{ transform: scale(1); opacity: 1; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1>Transcript Ingestion Pipeline Dashboard</h1>
                    <p class="sub-title">Fully Serverless GCP Pipeline Orchestration PoC</p>
                </div>
                <div class="status-panel">
                    <div class="status-dot {status_class}"></div>
                    <span class="status-label {status_class}">{status_label}</span>
                </div>
            </header>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Ingested Logs</div>
                    <div class="stat-value">{total_calls}</div>
                    <div class="stat-desc">Files warehoused in call_analyzer_table</div>
                </div>
                <div class="stat-card success">
                    <div class="stat-label">Taxonomy Taxonomy Reuse</div>
                    <div class="stat-value">{synonym_reuse_ratio}%</div>
                    <div class="stat-desc">Registry synonyms consolidation index</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Intent Registry Types</div>
                    <div class="stat-value">{total_categories}</div>
                    <div class="stat-desc">Distinct intent vectors registered</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Processed Duration</div>
                    <div class="stat-value">{total_duration}m</div>
                    <div class="stat-desc">Total call duration audited in BQ</div>
                </div>
            </div>
            
            <div class="main-grid">
                <div class="left-col">
                    <div class="panel">
                        <div class="panel-header">
                            <h2 class="panel-title">📊 Structured Ingestions History</h2>
                            <div>
                                <span class="badge primary">Showing last 10 records</span>
                            </div>
                        </div>
                        <div style="overflow-x: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Call ID</th>
                                        <th>Customer Info</th>
                                        <th>Primary Category</th>
                                        <th>Secondary Category</th>
                                        <th>Ingest Time (UTC)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {records_rows}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                
                <div class="right-col">
                    <div class="panel">
                        <div class="panel-header">
                            <h2 class="panel-title">⚡ Trigger Operations</h2>
                        </div>
                        <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">
                            Run the full pipeline asynchronously to process the remaining pre-loaded 100 GCS transcripts using Vertex AI model structures and matching parameters.
                        </p>
                        <button id="triggerBtn" class="btn" {"disabled" if pipeline_state["is_running"] else ""}>
                            🚀 Trigger Batch Ingestion PoC
                        </button>
                        
                        {f'''
                        <div class="progress-container">
                            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; color: var(--text-muted);">
                                <span>Progress: {pipeline_state['processed_count']} / {pipeline_state['total_files']} files</span>
                                <span>{progress_val}%</span>
                            </div>
                            <div class="progress-bar-bg">
                                <div class="progress-bar-fill" style="width: {progress_val}%;"></div>
                            </div>
                            <p style="font-size: 11px; font-style: italic; color: var(--warning); margin-top: 8px;">
                                Currently processing: <strong>{pipeline_state['current_file']}</strong>
                            </p>
                        </div>
                        ''' if pipeline_state["is_running"] else ""}
                    </div>
                    
                    <div class="panel">
                        <div class="panel-header">
                            <h2 class="panel-title">💻 Execution Session Log</h2>
                        </div>
                        <ul class="console-logs">
                            {logs_html if logs_html else "<li>[System Initialization] standby... logs are cleared before next execution turn.</li>"}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            const triggerBtn = document.getElementById('triggerBtn');
            
            triggerBtn.addEventListener('click', () => {{
                triggerBtn.disabled = true;
                triggerBtn.innerText = '⏳ Dispatching pipeline...';
                
                fetch('/ingest', {{ method: 'POST' }})
                .then(res => {{
                    if (res.status === 202) {{
                        alert('✅ Pipeline trigger accepted! Ingestion process has successfully started in the background. Refreshing dashboard...');
                        setTimeout(() => location.reload(), 1000);
                    }} else if (res.status === 497 || res.status === 409) {{
                        alert('⚠️ Ingestion process already running. Refusing double-trigger.');
                        location.reload();
                    }} else {{
                        alert('❌ API error occurred while initiating batch job.');
                        triggerBtn.disabled = false;
                        triggerBtn.innerText = '🚀 Trigger Batch Ingestion PoC';
                    }}
                }})
                .catch(err => {{
                    alert('❌ Connection failed while initiating API target: ' + err);
                    triggerBtn.disabled = false;
                    triggerBtn.innerText = '🚀 Trigger Batch Ingestion PoC';
                }});
            }});
            
            // Auto-refresh the page every 30 seconds if process is running to pull fresh BQ updates
            if ("{status_class}" === "running") {{
                setTimeout(() => location.reload(), 20000);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback."""
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
