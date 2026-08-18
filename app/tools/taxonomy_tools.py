import logging
from typing import Dict, Any, List
from google.cloud import bigquery
from google import genai

logger = logging.getLogger("a2a_wrapper")

def get_text_embedding(text: str) -> List[float]:
    """Generates a 768-dimension vector embedding using text-embedding-004."""
    client = genai.Client(
        vertexai=True,
        project="genai-demos-391416",
        location="us-central1"
    )
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=text
    )
    return response.embeddings[0].values

def semantic_taxonomy_lookup(primary: str, secondary: str, threshold: float = 0.80) -> Dict[str, Any]:
    """
    Looks up proposed intent reasons in BigQuery registry using Vector Distance.
    Enforces a matching threshold of 0.80 for aggressive synonymous category reuse,
    mapping inputs to the closest existing category or registering them if it's a unique intent.
    """
    client = bigquery.Client()
    proposed_label = f"{primary} - {secondary}"
    
    try:
        # Generate target embedding vector using Vertex AI
        proposed_vector = get_text_embedding(proposed_label)
        
        # Query existing taxonomy records in BQ using Cosine Similarity (1 - distance)
        query = """
            SELECT primary_category, secondary_category, 
                   (1 - ML.DISTANCE(category_embedding, @proposed_vec, 'COSINE')) AS similarity
            FROM `genai-demos-391416.call_analyzer.taxonomy_registry`
            ORDER BY similarity DESC
            LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("proposed_vec", "FLOAT64", proposed_vector)
            ]
        )
        
        query_job = client.query(query, job_config=job_config)
        results = list(query_job.result())
        
        if results and results[0].similarity >= threshold:
            match = results[0]
            logger.info(f"🧬 [Semantic Lookup Hit] Proposed '{proposed_label}' matches standard category: '{match.primary_category} - {match.secondary_category}' (Similarity: {match.similarity:.4f}). Enforcing reuse.")
            return {
                "status": "matched",
                "primary": match.primary_category,
                "secondary": match.secondary_category,
                "similarity": match.similarity
            }
            
        # Registry Miss: Register new intent category
        logger.info(f"✨ [Semantic Lookup Miss] Intent '{proposed_label}' not found above similarity threshold {threshold:.2f}. Registering new category.")
        
        insert_query = """
            INSERT INTO `genai-demos-391416.call_analyzer.taxonomy_registry` 
            (primary_category, secondary_category, category_embedding)
            VALUES (@pri, @sec, @vec)
        """
        
        insert_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("pri", "STRING", primary),
                bigquery.ScalarQueryParameter("sec", "STRING", secondary),
                bigquery.ArrayQueryParameter("vec", "FLOAT64", proposed_vector)
            ]
        )
        
        client.query(insert_query, job_config=insert_job_config).result()
        
        return {
            "status": "registered",
            "primary": primary,
            "secondary": secondary,
            "similarity": 1.0
        }
        
    except Exception as e:
        logger.error(f"❌ BigQuery semantic registry lookup error: {str(e)}")
        # In case of auth, database, or schema errors, gracefully fall back to proposed taxonomy tags
        return {
            "status": "fallback",
            "primary": primary,
            "secondary": secondary,
            "similarity": 0.0
        }
