import logging
from google.cloud import bigquery
from google.api_core.exceptions import Conflict

# Configure visual logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("setup_bq")

def setup_bigquery_resources():
    project_id = "genai-demos-391416"
    dataset_id = "call_analyzer"
    region = "us-central1"
    
    client = bigquery.Client()
    
    # 1. Create dataset if it does not exist
    dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = region
    dataset.description = "Conversational Agent Transcript Ingestion Warehouse and Registry"
    
    logger.info(f"📁 Bootstrapping BigQuery dataset '{project_id}.{dataset_id}' in region '{region}'...")
    try:
        dataset = client.create_dataset(dataset, timeout=30)
        logger.info(f"✅ Created BigQuery dataset '{dataset.dataset_id}'.")
    except Conflict:
        logger.info(f"ℹ️  Dataset '{dataset_id}' already exists. Transitioning to table generation...")
    except Exception as e:
        logger.error(f"❌ Failed to create dataset: {str(e)}")
        logger.error("💡 Please execute: gcloud auth application-default login")
        return

    # 2. Create processed transcripts target analytics table
    transcripts_table_id = f"{project_id}.{dataset_id}.call_analyzer_table"
    transcripts_ddl = f"""
        CREATE TABLE IF NOT EXISTS `{transcripts_table_id}` (
            -- Metadata Details
            call_id STRING NOT NULL,
            customer_id STRING NOT NULL,
            customer_name STRING,
            customer_type STRING,
            phone STRING,
            email STRING,
            services STRING,
            duration_minutes INT64,
            total_turns INT64,
            processed_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
            
            -- High-Reuse Intent Registry Details
            primary_reason STRING NOT NULL,
            secondary_reason STRING NOT NULL,
            
            -- Clustering Stage Records (Operational Costs Excluded)
            sequences ARRAY<STRUCT<
                sequence_name STRING,
                est_duration_seconds FLOAT64,
                turns ARRAY<STRUCT<
                    timestamp STRING,
                    speaker STRING,
                    text STRING,
                    dialogue_act STRING,
                    abstractive_title STRING
                >>
            >>
        )
        OPTIONS (
            description = "Analyzed, annotated, and clustered static conversational transcript registry"
        );
    """
    
    logger.info(f"📊 Re-creating analytics table '{transcripts_table_id}'...")
    try:
        client.query(f"DROP TABLE IF EXISTS `{transcripts_table_id}`").result()
        client.query(transcripts_ddl).result()
        logger.info("✅ Analytics table setup successfully completed.")
    except Exception as e:
        logger.error(f"❌ Failed to setup analytics table: {str(e)}")
        return

    # 3. Create vector semantic registry table
    registry_table_id = f"{project_id}.{dataset_id}.taxonomy_registry"
    registry_ddl = f"""
        CREATE TABLE IF NOT EXISTS `{registry_table_id}` (
            primary_category STRING NOT NULL,
            secondary_category STRING NOT NULL,
            category_embedding ARRAY<FLOAT64>,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
        )
        OPTIONS (
            description = "High-reuse taxonomy classification mapping registry with vector coordinates"
        );
    """
    
    logger.info(f"🧬 Re-creating semantic registry vector table '{registry_table_id}'...")
    try:
        client.query(f"DROP TABLE IF EXISTS `{registry_table_id}`").result()
        client.query(registry_ddl).result()
        logger.info("✅ Semantic registry table setup successfully completed.")
    except Exception as e:
        logger.error(f"❌ Failed to setup registry table: {str(e)}")
        return

    # 4. Seeds registry if empty
    logger.info("🌱 Seeding standard primary taxonomies in registry...")
    try:
        # Check if table already contains data to avoid duplication
        count_query = f"SELECT COUNT(1) as cnt FROM `{registry_table_id}`"
        cnt = list(client.query(count_query).result())[0].cnt
        
        if cnt > 0:
            logger.info(f"ℹ️  Semantic registry vector table already contains {cnt} indices. Skipping seed lifecycle.")
            logger.info("🎉 BigQuery resources initialization fully completed!")
            return
            
        # We define a seeding helper in Python utilizing mock embeddings vector lists to initialize the indices.
        # However, since seeding actual vectors requires calling models.embed_contents which triggers API quota calls,
        # we suggest calling text-embedding-004 on setup for the 5 target baseline categories!
        # Category Synonyms map:
        baseline_categories = [
            ("Account and PIN questions", "Security PIN Verification"),
            ("Billing problems", "Billing Disputes"),
            ("Technical issues", "Network Troubleshooting"),
            ("New orders", "Line Provisioning"),
            ("Payments", "Payment Agreements")
        ]
        
        from google import genai
        genai_client = genai.Client(
            vertexai=True,
            project="genai-demos-391416",
            location="us-central1"
        )
        
        for primary, secondary in baseline_categories:
            proposed = f"{primary} - {secondary}"
            logger.info(f"   └─ Embedding standard label: '{proposed}'...")
            
            emb_res = genai_client.models.embed_content(
                model="text-embedding-004",
                contents=proposed
            )
            vector = emb_res.embeddings[0].values
            
            insert_seed_query = f"""
                INSERT INTO `{registry_table_id}` (primary_category, secondary_category, category_embedding)
                VALUES (@pri, @sec, @vec)
            """
            seed_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("pri", "STRING", primary),
                    bigquery.ScalarQueryParameter("sec", "STRING", secondary),
                    bigquery.ArrayQueryParameter("vec", "FLOAT64", vector)
                ]
            )
            client.query(insert_seed_query, job_config=seed_config).result()
            
        logger.info("✅ Successfully seeded standard baseline taxonomies into vector registry.")
        logger.info("🎉 BigQuery resources initialization fully completed!")
        
    except Exception as e:
        logger.error(f"⚠️  Database seeding warning: {str(e)}")
        logger.error("💡 You can run seeding manually once credentials refresh successfully.")

if __name__ == "__main__":
    setup_bigquery_resources()
