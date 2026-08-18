import os
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field
from typing import List

# Tenacity imports for elegant retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Google GenAI imports
from google import genai
from google.genai import types
from google.genai.errors import APIError

# ---------------------------------------------------------------------------
# Structured Output Schema Definitions using Pydantic
# ---------------------------------------------------------------------------
class TranscriptTurn(BaseModel):
    timestamp: str = Field(description="Relative timestamp in 'MM:SS' format from the start of the call (e.g. '00:00', '00:14', '01:05'), incrementing naturally based on spoken duration.")
    speaker: str = Field(description="Must be either 'Agent' or 'User'")
    text: str = Field(description="The verbatim spoken utterance, complete and realistic.")

class CallTranscript(BaseModel):
    turns: List[TranscriptTurn] = Field(description="The sequential back-and-forth turns of the telephone call")

# ---------------------------------------------------------------------------
# Core Transcripts Generator
# ---------------------------------------------------------------------------
class DatasetGenerator:
    def __init__(self, concurrency=6):
        self.concurrency = concurrency
        self.output_dir = "transcripts"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load user pool and call specifications
        with open("users.json", "r") as f:
            self.users = {u["customer_id"]: u for u in json.load(f)}
            
        with open("call_specs.json", "r") as f:
            self.call_specs = json.load(f)
            
        # Load or initialize index file
        self.index_path = "transcripts_index.json"
        self.index_data = {}
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r") as f:
                    self.index_data = json.load(f)
            except Exception:
                pass

    def save_index(self):
        with open(self.index_path, "w") as f:
            json.dump(self.index_data, f, indent=2)

    def write_markdown_transcript(self, spec, customer, turns):
        """Generates a highly readable markdown format for human inspection."""
        md_lines = []
        md_lines.append(f"# Call Transcript: {spec['call_id']}")
        md_lines.append("")
        md_lines.append("## Call Metadata")
        md_lines.append(f"- **Call ID:** {spec['call_id']}")
        md_lines.append(f"- **Customer ID:** {spec['customer_id']}")
        md_lines.append(f"- **Customer Name:** {customer['name']}")
        md_lines.append(f"- **Customer Type:** {spec['customer_type']}")
        md_lines.append(f"- **Duration:** {spec['duration_minutes']} minutes")
        md_lines.append("")
        md_lines.append("## Account Information")
        md_lines.append(f"- **Phone Number:** {customer['phone']}")
        md_lines.append(f"- **Email Address:** {customer['email']}")
        md_lines.append(f"- **Plan/Services:** {customer['services']}")
        md_lines.append(f"- **Payment Standing:** {customer['standing']}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")
        md_lines.append("## Transcript Dialogue")
        md_lines.append("")
        
        for turn in turns:
            timestamp = turn["timestamp"]
            speaker = turn["speaker"]
            text = turn["text"]
            
            if speaker == "Agent":
                md_lines.append(f"**[{timestamp}] [Agent]:** {text}")
            else:
                md_lines.append(f"**[{timestamp}] [User] ({customer['name']}):** {text}")
            md_lines.append("")
            
        md_path = os.path.join(self.output_dir, f"{spec['call_id']}.md")
        with open(md_path, "w") as f:
            f.write("\n".join(md_lines))

    # Define robust retry with backoff for API errors
    # Wait: 4s, 8s, 16s, etc., up to 5 retries
    @retry(
        retry=retry_if_exception_type((APIError, Exception)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=True
    )
    def generate_single_call(self, spec):
        customer = self.users[spec["customer_id"]]
        
        # Initialize a dedicated, thread-local GenAI client to isolate gRPC connection state in multithreading
        client = genai.Client(
            vertexai=True,
            project="genai-demos-391416",
            location="us-central1"
        )
        
        # Linear turn density model: approx 6 turns per min, min 5 turns per min
        duration_minutes = spec["duration_minutes"]
        approx_turns = duration_minutes * 6
        min_turns = duration_minutes * 5
        
        system_instruction = f"""You are an elite, highly detailed dataset generator specializing in telecommunications call center logs.
Your task is to generate a highly realistic, verbatim transcript of a telephone call between a Customer Service Agent and a Customer (User) based on the provided specifications.

CRITICAL PROTOCOLS AND QUALITY CONTROLS:
1. Tone & Professionalism:
   - The Agent must sound professional, polite, helpful, and patient. The agent is an employee of **Cymbal Telecom** and must greet the customer on behalf of **Cymbal Telecom** (e.g., 'Thank you for calling Cymbal Telecom. My name is [Agent]. How can I help you today?').
   - The Agent must follow typical corporate standard scripts: greeting the caller, asking for identification, validating account information, taking active diagnostic/troubleshooting steps, confirming resolution, asking if anything else is needed, and closing with a professional corporate sign-off.
   - The User must sound like a real customer calling their telecom provider. Their emotional profile and tone should depend on the call category:
     * "Technical issues e.g. outages": Customer might be frustrated, working from home with a deadline, confused about hardware rebooting, or relieved when resolved.
     * "Billing problems": Customer is usually concerned, demanding clear billing item explanations, wanting service tier pro-ration credits, and highly focused on pricing numbers.
     * "New orders": Customer is generally curious, interested, receptive to features, and careful about setup/activation fees.
     * "Payments": Customer is sometimes stressed, apologetic, or embarrassed about credit card expiration or temporary cash hardships.
     * "Account and PIN questions": Customer wants fast service, verification checks, or voicemail resets.

2. Verbatim, No Summarization:
   - You MUST write out the FULL word-for-word spoken conversation from greeting to sign-off.
   - Do NOT use placeholders, shorthand, bracketed summaries, or skip parts like "[agent reviews bill...]" or "[troubleshooting takes place...]". Everything must be a spoken line.
   - If action/checks are occurring, represent them spoken: Agent explains they are checking the network/ledger and will take 20 seconds, asks customer if they mind, customer says yes, agent returns with results and thanks customer for patience.

3. Pacing, Turn Count, and Realism:
   - The caller spent {duration_minutes} minutes on this call.
   - An average telecom support call of this duration contains approximately {approx_turns} individual turns (back-and-forth lines).
   - To make this transcript highly realistic, you MUST generate at least {min_turns} distinct turns. Rushing to a resolution in 10 turns for a 15-minute call is a severe failure. Write a long, thorough conversation that walks through each detail in standard pace.

4. Domain Accuracy & Cymbal Branding:
   - Use correct telecom jargon: ONT, DSL, coax, 5G mesh router node, pro-rated lines, billing cycle invoice, state tax exemption, automatic debit ACH, expired card on file, mobile roaming partner networks, voicemail mailbox PIN, porting out/in ICCID.
   - The telecom provider company name in all contexts (greetings, product descriptions, billing records, contracts, Wi-Fi SSID network names, support team departments) MUST ALWAYS be **Cymbal Telecom** (or **Cymbal** for short). Do NOT use other telecom brand names (such as Omni Telecom, Telecom Solutions, OmniLink, OmniCom, etc.). Any Wi-Fi network names must be 'Cymbal Wi-Fi' or 'Cymbal Telecom Wi-Fi'.

5. Turn-by-Turn Timestamps:
   - Each turn MUST include a relative timestamp in "MM:SS" format (e.g. "00:00" for the first speaker turn, and naturally incrementing based on the length of each speaker's turn).
   - Timestamp increments must realistically match spoken pacing: short sentences (e.g. 5-10 words) take 2-4 seconds; medium paragraphs take 10-15 seconds; holds or ONT/router power-cycles take 20-40 seconds of conversational pause.
   - The final turn of the call must end close to the target duration (e.g. for a {duration_minutes}-minute call, the final timestamp must be between "{duration_minutes - 1:02d}:40" and "{duration_minutes:02d}:15").
"""

        prompt = f"""Generate a detailed, verbatim transcript for a call based on these specifications:

Call Specifications:
- Call ID: {spec['call_id']}
- Target Duration: {spec['duration_minutes']} minutes
- Required Minimum Speaker Turns: {min_turns} turns
- Customer Category: {spec['customer_type']}
- Core Category: {spec['category']}
- Core Topic: {spec['topic']}
- Specific Scenario Blueprint: {spec['summary']}

Customer Profile Context:
- Customer Name: {customer['name']}
- Customer ID: {customer['customer_id']}
- Contact Phone: {customer['phone']}
- Contact Email: {customer['email']}
- Account Security PIN: {customer['pin']}
- Subscribed Services/Plan: {customer['services']}
- Account standing: {customer['standing']}

Core Flow Directives:
- At the start, the Agent MUST greet the customer on behalf of **Cymbal Telecom** and ask the caller to confirm their Customer ID and security PIN to verify security credentials before sharing plan or billing specifics.
- The company name throughout the call for all support, technical, or network services, including Wi-Fi signals (e.g. 'Cymbal Wi-Fi') must be **Cymbal Telecom** (or **Cymbal**). Do NOT use any other telecom provider name.
- The transcript must expand to a detailed dialogue of at least {min_turns} turns to reflect the {duration_minutes}-minute duration.
- The turns must contain realistic incremental relative timestamps in "MM:SS" format, starting at "00:00" and ending close to "{duration_minutes:02d}:00" at the final turn.
- Retain exact pro-rations, calculations, technical diagnostics, or device options in clear spoken terms.
- Output strictly in JSON adhering to the specified schema: an array of speaker turns with 'timestamp', 'speaker' and 'text' fields.
"""

        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CallTranscript,
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        
        # Load raw JSON from text response
        raw_json = json.loads(response.text.strip())
        turns = raw_json["turns"]
        
        # Perform structural validations
        if not turns or len(turns) < 3:
            raise ValueError("Generated transcript contains insufficient turns.")
            
        return turns

    def process_call(self, spec):
        call_id = spec["call_id"]
        json_path = os.path.join(self.output_dir, f"{call_id}.json")
        md_path = os.path.join(self.output_dir, f"{call_id}.md")
        
        # Check if already generated (Resume support!)
        if os.path.exists(json_path) and os.path.exists(md_path) and call_id in self.index_data and self.index_data[call_id]["status"] == "SUCCESS":
            print(f"  [{call_id}] Already generated. Skipping.")
            return call_id, "SKIPPED", 0
            
        print(f"  [{call_id}] Generating transcript ({spec['category']} | {spec['duration_minutes']} mins | min {spec['duration_minutes']*5} turns)...")
        start_time = time.time()
        
        try:
            turns = self.generate_single_call(spec)
            elapsed = time.time() - start_time
            
            # Form complete payload
            customer = self.users[spec["customer_id"]]
            payload = {
                "metadata": {
                    "call_id": spec["call_id"],
                    "customer_id": spec["customer_id"],
                    "customer_name": customer["name"],
                    "customer_type": spec["customer_type"],
                    "phone": customer["phone"],
                    "email": customer["email"],
                    "services": customer["services"],
                    "duration_minutes": spec["duration_minutes"],
                    "total_turns": len(turns)
                },
                "transcript": turns
            }
            
            # Save JSON transcript
            with open(json_path, "w") as f:
                json.dump(payload, f, indent=2)
                
            # Save Markdown transcript
            self.write_markdown_transcript(spec, customer, turns)
            
            # Update index
            self.index_data[call_id] = {
                "call_id": spec["call_id"],
                "customer_id": spec["customer_id"],
                "customer_name": customer["name"],
                "customer_type": spec["customer_type"],
                "category": spec["category"],
                "topic": spec["topic"],
                "duration_minutes": spec["duration_minutes"],
                "total_turns": len(turns),
                "generation_time_seconds": round(elapsed, 2),
                "status": "SUCCESS"
            }
            self.save_index()
            
            print(f"  [{call_id}] Completed successfully in {elapsed:.1f}s! (turns: {len(turns)})")
            return call_id, "SUCCESS", len(turns)
            
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  [{call_id}] FAILED after {elapsed:.1f}s: {e}")
            
            self.index_data[call_id] = {
                "call_id": spec["call_id"],
                "customer_id": spec["customer_id"],
                "customer_name": spec["customer_name"],
                "customer_type": spec["customer_type"],
                "category": spec["category"],
                "topic": spec["topic"],
                "duration_minutes": spec["duration_minutes"],
                "status": f"FAILED: {str(e)}"
            }
            self.save_index()
            return call_id, "FAILED", 0

    def run(self):
        total_calls = len(self.call_specs)
        print(f"Starting pipeline to generate {total_calls} synthetic transcripts...")
        print(f"Using a concurrency pool size of: {self.concurrency} workers.")
        
        success_count = 0
        skipped_count = 0
        failed_count = 0
        total_turns = 0
        
        start_pipeline = time.time()
        
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            # Submit all calls to executor pool
            future_to_spec = {executor.submit(self.process_call, spec): spec for spec in self.call_specs}
            
            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    call_id, result, turns = future.result()
                    if result == "SUCCESS":
                        success_count += 1
                        total_turns += turns
                    elif result == "SKIPPED":
                        skipped_count += 1
                        # If skipped, retrieve turns count from existing file
                        json_path = os.path.join(self.output_dir, f"{call_id}.json")
                        try:
                            with open(json_path, "r") as f:
                                payload = json.load(f)
                                total_turns += len(payload["transcript"])
                        except Exception:
                            pass
                    else:
                        failed_count += 1
                except Exception as exc:
                    print(f"  System error processing future for {spec['call_id']}: {exc}")
                    failed_count += 1
                    
                completed = success_count + skipped_count + failed_count
                pct = (completed / total_calls) * 100
                print(f"Progress: {completed}/{total_calls} ({pct:.1f}%) | Success: {success_count} | Skipped: {skipped_count} | Failed: {failed_count}")
                
        pipeline_elapsed = time.time() - start_pipeline
        print("\n========================================================")
        print("PIPELINE EXECUTION COMPLETE")
        print("========================================================")
        print(f"Total specs processed: {total_calls}")
        print(f"  - Successfully generated: {success_count}")
        print(f"  - Reused/Skipped:         {skipped_count}")
        print(f"  - Failed to generate:     {failed_count}")
        print(f"Total conversational turns generated: {total_turns}")
        print(f"Average turns per conversation:       {total_turns / (success_count + skipped_count):.1f}" if (success_count + skipped_count) > 0 else "0.0")
        print(f"Total time elapsed:                   {pipeline_elapsed:.1f} seconds ({pipeline_elapsed/60:.1f} minutes)")
        print(f"Average generation speed:             {pipeline_elapsed / max(1, success_count):.2f} seconds/transcript")
        print("========================================================")

if __name__ == "__main__":
    # Target concurrency of 12 offers doubled velocity while keeping safety margins under rate limits
    generator = DatasetGenerator(concurrency=12)
    generator.run()
