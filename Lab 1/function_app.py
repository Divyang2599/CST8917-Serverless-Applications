import azure.functions as func
import logging
import json
import re
import os
import uuid
from datetime import datetime, timezone
from azure.cosmos import CosmosClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ---- Cosmos DB config ----
COSMOS_CONNECTION_STRING = os.environ.get("COSMOS_CONNECTION_STRING")
DATABASE_NAME = "TextAnalyzerDB"
CONTAINER_NAME = "AnalysisResults"


def get_container():
    """Connect to Cosmos and return the container client."""
    client = CosmosClient.from_connection_string(COSMOS_CONNECTION_STRING)
    database = client.get_database_client(DATABASE_NAME)
    return database.get_container_client(CONTAINER_NAME)


@app.route(route="TextAnalyzer")
def TextAnalyzer(req: func.HttpRequest) -> func.HttpResponse:
    """Analyzes text, stores the result in Cosmos DB, and returns it."""
    logging.info('Text Analyzer API was called!')

    text = req.params.get('text')
    if not text:
        try:
            req_body = req.get_json()
            text = req_body.get('text')
        except ValueError:
            pass

    if text:
        words = text.split()
        word_count = len(words)
        char_count = len(text)
        char_count_no_spaces = len(text.replace(" ", ""))
        sentence_count = len(re.findall(r'[.!?]+', text)) or 1
        paragraph_count = len([p for p in text.split('\n\n') if p.strip()])
        reading_time_minutes = round(word_count / 200, 1)
        avg_word_length = round(char_count_no_spaces / word_count, 1) if word_count > 0 else 0
        longest_word = max(words, key=len) if words else ""

        record = {
            "id": str(uuid.uuid4()),
            "analysis": {
                "wordCount": word_count,
                "characterCount": char_count,
                "characterCountNoSpaces": char_count_no_spaces,
                "sentenceCount": sentence_count,
                "paragraphCount": paragraph_count,
                "averageWordLength": avg_word_length,
                "longestWord": longest_word,
                "readingTimeMinutes": reading_time_minutes
            },
            "metadata": {
                "analyzedAt": datetime.now(timezone.utc).isoformat(),
                "textPreview": text[:100] + "..." if len(text) > 100 else text
            }
        }

        try:
            container = get_container()
            container.create_item(body=record)
            record["saved"] = True
            logging.info(f"Saved analysis {record['id']} to Cosmos DB.")
        except Exception as e:
            record["saved"] = False
            logging.error(f"Failed to save to Cosmos DB: {e}")

        return func.HttpResponse(
            json.dumps(record, indent=2),
            mimetype="application/json",
            status_code=200
        )

    else:
        instructions = {
            "error": "No text provided",
            "howToUse": {
                "option1": "Add ?text=YourText to the URL",
                "option2": "Send a POST request with JSON body: {\"text\": \"Your text here\"}",
                "example": "https://your-function-url/api/TextAnalyzer?text=Hello world"
            }
        }
        return func.HttpResponse(
            json.dumps(instructions, indent=2),
            mimetype="application/json",
            status_code=400
        )


@app.route(route="GetAnalysisHistory")
def GetAnalysisHistory(req: func.HttpRequest) -> func.HttpResponse:
    """Returns the most recent analysis results from Cosmos DB."""
    logging.info('GetAnalysisHistory API was called!')

    # Optional ?limit=N (default 10), validated and capped
    try:
        limit = int(req.params.get('limit', 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(limit, 100))

    try:
        container = get_container()
        # limit is a validated int, so it's safe to inline in the query
        query = f"SELECT * FROM c ORDER BY c.metadata.analyzedAt DESC OFFSET 0 LIMIT {limit}"
        items = list(container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))

        results = [
            {
                "id": item.get("id"),
                "analysis": item.get("analysis"),
                "metadata": item.get("metadata")
            }
            for item in items
        ]

        response_data = {
            "count": len(results),
            "results": results
        }
        return func.HttpResponse(
            json.dumps(response_data, indent=2),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        logging.error(f"Failed to query Cosmos DB: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Could not retrieve history", "details": str(e)}, indent=2),
            mimetype="application/json",
            status_code=500
        )