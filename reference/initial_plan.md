# Technical Specification & Implementation Plan: Belgian Constitutional Court RAG Search Engine

This document outlines the architecture, pipeline, and code required to build a zero-cost, zero-maintenance, user-facing RAG (Retrieval-Augmented Generation) system for Belgian Constitutional Court rulings.

---

## 1. Architecture Overview

```
[ Local PC / GitHub ] 
         │ (1. Raw PDFs to Markdown)
         ▼
[ GitHub Repository ] ──(2. GitHub Action Trigger)──► [ Python DB Builder ]
                                                              │
                                                     (3. Builds SQLite FTS5)
                                                              ▼
[ Scaleway Serverless Function ] ◄──(5. Downloads)─── [ Scaleway S3 Bucket ]
  (Python 3.11 Runtime in Paris)                        (Hosts `cases.db`)
         ▲
         │ (6. HTTPS Query via OpenAPI / JSON)
         ▼
[ Microsoft Copilot / Custom GPT ] ──(7. Synthesizes Answer)──► [ Non-Technical End User ]
```

* **Data Pipeline**: Cases are stored as Markdown in GitHub. A GitHub Action compiles them into a single SQLite database (`cases.db`) featuring `FTS5` full-text search.
* **Storage Layer**: Scaleway Object Storage (Paris, `fr-par`) hosts the compiled `cases.db`.
* **Compute Layer**: Scaleway Serverless Functions (Python) processes search queries, fetching and querying `cases.db` in `/tmp` ephemeral storage.
* **Client Layer**: Microsoft Copilot / OpenAI Custom GPT calls the Scaleway Function via an OpenAPI schema, presenting citations to the user.
* **Hosting Cost**: **€0.00/month** (leveraging Scaleway's free monthly tier of 1,000,000 requests and 75,000 GB-s compute).

---

## 2. Component Implementation & Code Snippets

### Component A: Index Generator Script (`scripts/build_db.py`)
This script runs in CI/CD, parsing Markdown files with YAML frontmatter into a lightweight SQLite FTS5 database.

```python
import os
import re
import sqlite3
import yaml

DB_FILE = "cases.db"
MARKDOWN_DIR = "./cases"

def init_db():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Create Full-Text Search (FTS5) table with BM25 ranking capability
    cursor.execute("""
        CREATE VIRTUAL TABLE case_passages USING fts5(
            case_number,
            ruling_date,
            title,
            passage_text,
            tokenize='unicode61'
        );
    """)
    conn.commit()
    return conn

def parse_markdown_files(conn):
    cursor = conn.cursor()
    
    for root, _, files in os.walk(MARKDOWN_DIR):
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Extract YAML frontmatter
                parts = re.split(r"^---$", content, flags=re.MULTILINE)
                if len(parts) >= 3:
                    metadata = yaml.safe_load(parts[1])
                    body = "---".join(parts[2:])
                else:
                    metadata = {}
                    body = content
                
                case_num = str(metadata.get("case_number", "Unknown"))
                ruling_date = str(metadata.get("ruling_date", "Unknown"))
                title = metadata.get("title", file)
                
                # Split body into logical paragraphs/passages (~500 words)
                passages = [p.strip() for p in body.split("\n\n") if len(p.strip()) > 50]
                
                for passage in passages:
                    cursor.execute("""
                        INSERT INTO case_passages (case_number, ruling_date, title, passage_text)
                        VALUES (?, ?, ?, ?)
                    """, (case_num, ruling_date, title, passage))
                    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    connection = init_db()
    parse_markdown_files(connection)
    print("SQLite index built successfully.")
```

---

### Component B: GitHub Actions Workflow (`.github/workflows/deploy.yml`)
Automates building `cases.db` on every commit to `main` and uploads it to Scaleway Object Storage.

```yaml
name: Build and Deploy Search Index

on:
  push:
    branches: [ main ]
    paths:
      - 'cases/**'

jobs:
  build-and-upload:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: pip install pyyaml boto3

      - name: Build SQLite Index
        run: python scripts/build_db.py

      - name: Upload to Scaleway S3
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.SCW_ACCESS_KEY }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.SCW_SECRET_KEY }}
          ENDPOINT_URL: "https://s3.fr-par.scw.cloud"
          BUCKET_NAME: "belgian-court-cases"
        run: |
          python -c "
          import boto3, os
          s3 = boto3.client('s3',
                            endpoint_url=os.environ['ENDPOINT_URL'],
                            aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                            aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'])
          s3.upload_file('cases.db', os.environ['BUCKET_NAME'], 'cases.db', ExtraArgs={'ACL': 'public-read'})
          "
```

---

### Component C: Scaleway Serverless Function (`src/handler.py`)
This Python handler processes search requests from Copilot/ChatGPT, querying `cases.db` cached in `/tmp`.

```python
import json
import os
import sqlite3
import urllib.request

DB_PATH = "/tmp/cases.db"
# Replace with actual Scaleway S3 Public URL
DB_URL = "https://belgian-court-cases.s3.fr-par.scw.cloud/cases.db"

def handle(event, context):
    # 1. Download database to ephemeral /tmp storage if cold start
    if not os.path.exists(DB_PATH):
        urllib.request.urlretrieve(DB_URL, DB_PATH)

    # 2. Extract user search query
    query_params = event.get("queryStringParameters") or {}
    user_query = query_params.get("q", "").strip()

    if not user_query:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Query parameter 'q' is required."})
        }

    # Format query for SQLite FTS5 (BM25 keyword matching)
    fts_query = " OR ".join([f'"{word}"' for word in user_query.split() if len(word) > 2])

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Execute BM25 ranking query
        cursor.execute("""
            SELECT case_number, ruling_date, title, passage_text, rank
            FROM case_passages
            WHERE case_passages MATCH ?
            ORDER BY rank
            LIMIT 5
        """, (fts_query,))
        
        rows = cursor.fetchall()
        conn.close()

        results = [
            {
                "case_number": r[0],
                "ruling_date": r[1],
                "title": r[2],
                "excerpt": r[3]
            }
            for r in rows
        ]

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"query": user_query, "results": results})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)})
        }
```

---

### Component D: OpenAPI Specification (`openapi.json`)
Import this specification into Microsoft Copilot Studio or Custom GPT Builder.

```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Belgian Constitutional Court RAG API",
    "description": "API for retrieving relevant passages from Belgian Constitutional Court rulings.",
    "version": "1.0.0"
  },
  "servers": [
    {
      "url": "https://belgiancourt.functions.fnc.fr-par.scw.cloud"
    }
  ],
  "paths": {
    "/": {
      "get": {
        "summary": "Search Court Rulings",
        "description": "Performs BM25 search over Constitutional Court case texts.",
        "operationId": "searchCases",
        "parameters": [
          {
            "name": "q",
            "in": "query",
            "description": "Legal topic, case number, or keywords (e.g. 'environmental permits')",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Matching passages returned successfully.",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "results": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "case_number": { "type": "string" },
                          "ruling_date": { "type": "string" },
                          "title": { "type": "string" },
                          "excerpt": { "type": "string" }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

---

## 3. Developer Task Checklist

* [ ] **Environment Setup**:
  * Create a free account on **Scaleway** and set up an S3 Bucket named `belgian-court-cases` in region `fr-par`.
  * Set `SCW_ACCESS_KEY` and `SCW_SECRET_KEY` in GitHub Repo Secrets.
* [ ] **Pipeline Execution**:
  * Verify `scripts/build_db.py` parses local Markdown files in `/cases` and properly outputs `cases.db`.
  * Trigger GitHub Action to confirm `cases.db` successfully uploads to Scaleway S3 with public read access.
* [ ] **Serverless Deployment**:
  * Deploy `src/handler.py` to Scaleway Serverless Functions (Python 3.11 runtime).
  * Verify execution via `curl "https://<your-function-url>?q=environnement"`.
* [ ] **Client Integration**:
  * Upload `openapi.json` into Microsoft Copilot Studio (Declarative Agent) or ChatGPT Custom GPT.
  * Define system prompt instructions requiring the agent to always cite `case_number` and `ruling_date` when outputting answers.
