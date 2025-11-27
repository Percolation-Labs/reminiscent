# REM System Walkthrough

Complete hands-on guide to explore REM's progressive memory enrichment from raw files to intelligent knowledge graphs.

## Prerequisites

Before starting, choose your installation method and ensure you have API keys configured.

### Choose Your Installation Method

| Method | Description | Best For | Setup Time |
|--------|-------------|----------|------------|
| **PyPI Package** | `pip install remdb[all]` + bring your own PostgreSQL | Production usage, embedding in projects | 5 min |
| **Docker Compose** | Complete stack (PostgreSQL + API) in containers | Quick testing, zero Python install | 2 min |
| **Hybrid** | Docker PostgreSQL + local Python package | Development, debugging, CLI access | 5 min |

### Required API Keys

REM needs at least one LLM provider API key. We recommend having all three:

| Provider | Required For | Get Key From | Environment Variable |
|----------|--------------|--------------|---------------------|
| **OpenAI** | Embeddings (text-embedding-3-small) | https://platform.openai.com/api-keys | `OPENAI_API_KEY` or `LLM__OPENAI_API_KEY` |
| **Anthropic** | Chat completions (Claude Sonnet 4.5) | https://console.anthropic.com/settings/keys | `ANTHROPIC_API_KEY` or `LLM__ANTHROPIC_API_KEY` |
| **Cerebras** | Fast inference (optional) | https://cloud.cerebras.ai/platform | `CEREBRAS_API_KEY` or `LLM__CEREBRAS_API_KEY` |

**Note**: REM settings support both prefixed (`LLM__*_API_KEY`) and unprefixed API keys. Use whichever is convenient.

### Setup Instructions by Method

#### PyPI Package Setup
```bash
# Install package
pip install remdb[all]

# Set up API keys
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export CEREBRAS_API_KEY="csk-..."  # Optional

# Configure REM (creates config file and optionally installs database)
rem configure --install

# Verify installation
rem --help
```

#### Docker Compose Setup
```bash
# Clone repository
git clone https://github.com/mr-saoirse/remstack.git
cd remstack/rem

# Set up API keys (MUST be exported BEFORE docker compose up)
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Or create .env file
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
EOF

# Start services
docker compose up -d

# Verify
curl http://localhost:8000/health
docker exec rem-api rem --help
```

#### Hybrid Setup (Recommended for Development)
```bash
# Start PostgreSQL only
cd remstack/rem
docker compose up postgres -d

# Install package
pip install remdb[all]

# Configure connection
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Verify
rem --help
```

---

## Step 0: Explore Available Commands

Before we begin, familiarize yourself with REM's CLI commands.

### Main CLI Commands

| Command | Description | Example |
|---------|-------------|---------|
| `rem --help` | Show all available commands | `rem --help` |
| `rem configure` | Configure REM installation | `rem configure --install` |
| `rem db` | Database operations (migrate, status, schema) | `rem db migrate` |
| `rem process ingest` | Ingest file into memory (storage + parsing + embedding) | `rem process ingest path/to/file.pdf` |
| `rem process files` | Batch process existing files (re-run extractors) | `rem process files --status pending` |
| `rem dreaming` | Run knowledge extraction workers | `rem dreaming full` |
| `rem ask` | Query REM memory conversationally | `rem ask "What documents do we have?"` |
| `rem serve` | Start FastAPI server (chat completions + MCP) | `rem serve` |
| `rem mcp` | Run standalone MCP server | `rem mcp` |
| `rem experiments` | Manage evaluation experiments | `rem experiments run my-exp` |
| `rem dev` | Development utilities | `rem dev list-schemas` |

### Getting Help

```bash
# Global help
rem --help

# Command-specific help
rem db --help
rem process --help
rem dreaming --help
rem ask --help

# Subcommand help
rem db schema --help
rem dreaming full --help
rem process files --help
```

**Docker Users**: Prefix all commands with `docker exec rem-api`:
```bash
docker exec rem-api rem --help
docker exec rem-api rem ask "What is REM?" --user-id user-123
```

---

## Step 1: Ingest Your First File

Let's upload a PDF document and observe how REM stores and processes it.

### 1.1 Prepare a Test PDF

Download or create a test PDF. We recommend saving this to your Downloads folder to avoid modifying the repository.

```bash
# Check if file exists, otherwise download a sample research paper
[ -f ~/Downloads/sample.pdf ] || curl -L -o ~/Downloads/sample.pdf https://arxiv.org/pdf/2310.06825.pdf
```

### 1.2 Process the File

```bash
# Process the PDF from Downloads
rem process ingest ~/Downloads/sample.pdf --user-id user-123

# Docker users:
# First copy the file into the container
docker cp ~/Downloads/sample.pdf rem-api:/app/sample.pdf
# Then ingest it
docker exec rem-api rem process ingest /app/sample.pdf --user-id user-123
```

**What happens:**
1. File is uploaded to storage (local filesystem by default, S3 if configured)
2. Content is extracted using provider-specific extractors (PDF parser, vision models, etc.)
3. Text is chunked semantically using `semchunk`
4. Chunks are embedded using OpenAI `text-embedding-3-small`
5. `File` entity created in database
6. `Resource` entities created for each chunk

### 1.3 Observe Storage Locations

#### File Storage (Configurable)

**Local Filesystem** (default):
```bash
# Files stored at: ~/.rem/files/{user_id}/{file_id}/
ls -la ~/.rem/files/user-123/

# Parsed content stored at: ~/.rem/files/{user_id}/{file_id}/parsed/
cat ~/.rem/files/user-123/{file-id}/parsed/content.txt
```

**S3 Storage** (if configured):
```bash
# Set S3 configuration
export S3__BUCKET_NAME="my-rem-bucket"
export S3__PREFIX="rem-data/"
export AWS_REGION="us-east-1"

# Files will be stored at: s3://{bucket}/{prefix}/files/{user_id}/{file_id}/
aws s3 ls s3://my-rem-bucket/rem-data/files/user-123/
```

**Configuration in `~/.rem/config.yaml`**:
```yaml
storage:
  type: s3  # or "filesystem"
  bucket: my-rem-bucket
  prefix: rem-data/
```

### 1.4 Verify Database Updates

```bash
# Check database status
rem db status

# Query files directly (requires psql)
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT id, name, mime_type, processing_status FROM files WHERE user_id = 'user-123' LIMIT 5;"

# Query resources (chunks)
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT id, category, LEFT(text_content, 50) as preview FROM resources WHERE user_id = 'user-123' LIMIT 5;"
```

**What you'll see:**
- `files` table: 1 row with `processing_status = 'completed'`
- `resources` table: N rows (one per chunk) with embeddings in `embedding` column
- `kv_store` table: Cached lookup entries for O(1) queries

---

## Step 2: Query Your Memory

Now that we have data, let's query it using both CLI and API.

### 2.1 CLI: Ask a Question

```bash
# Ask about the document (creates a new session)
rem ask "What is this document about?" --user-id user-123
```

**What happens:**
1. Agent receives query + retrieves relevant resources via REM `SEARCH` query
2. Semantic search using pgvector finds top-k most similar chunks
3. Agent synthesizes answer from retrieved context
4. Session ID generated and returned (look for "Session ID: ..." in output)

### 2.2 CLI: Session Continuity with Explicit Session ID

**IMPORTANT**: `rem ask` is stateless by default. To maintain conversation context for follow-up questions, you **must manually provide the session ID** from the previous response.

```bash
# Start a new session with explicit ID
rem ask "Summarize the document" --user-id user-123 --session-id walkthrough-session

# Continue conversation - you MUST provide the same session ID
rem ask "What are the limitations?" --user-id user-123 --session-id walkthrough-session

# Another follow-up - still using the same session ID
rem ask "What are the main findings?" --user-id user-123 --session-id walkthrough-session
```

**Key Points:**
- Each `rem ask` call is independent unless you provide `--session-id`
- Without `--session-id`, follow-up questions like "What is the title?" will fail (no context)
- Copy the session ID from previous responses or use a memorable ID like "walkthrough-session"
- The API stores sessions in the database, but the CLI doesn't automatically maintain state

### 2.3 API: Chat Completions (Non-Streaming)

```bash
# Start API server (if not already running)
rem serve &

# Wait for startup
sleep 5

# Make chat completion request
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user-123" \
  -H "X-Session-Id: api-session-1" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "What documents have been uploaded?"}
    ],
    "stream": false
  }'
```

### 2.4 API: Chat Completions (Streaming)

```bash
# Streaming request
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user-123" \
  -H "X-Session-Id: api-session-2" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "Tell me about the methodology"}
    ],
    "stream": true
  }'
```

**What you'll see:**
```
data: {"id":"msg_123","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"},"index":0}]}

data: {"id":"msg_123","object":"chat.completion.chunk","choices":[{"delta":{"content":"The"},"index":0}]}

data: {"id":"msg_123","object":"chat.completion.chunk","choices":[{"delta":{"content":" methodology"},"index":0}]}

...

data: [DONE]
```

### 2.5 Verify Session Messages Are Stored

```bash
# Check session messages
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT session_id, message_type, LEFT(content, 50) as preview, created_at
   FROM messages
   WHERE user_id = 'user-123'
   ORDER BY created_at DESC
   LIMIT 10;"
```

**What you'll see:**
- Messages grouped by `session_id` (no separate sessions table)
- Both CLI (`rem ask`) and API messages stored in `messages` table
- Each turn creates 2 rows: user message (message_type='user') + assistant response (message_type='assistant')
- Messages with same `session_id` provide conversation context

### 2.6 Follow-Up Questions with Session Context

```bash
# First question
rem ask "What is the main topic?" --user-id user-123 --session-id smart-session

# Follow-up (no need to repeat context, but MUST provide same session-id)
rem ask "What are the implications?" --user-id user-123 --session-id smart-session

# Another follow-up (still using same session-id)
rem ask "Summarize that in 3 bullet points" --user-id user-123 --session-id smart-session
```

**Why this works:**
- Agent has access to full session history via `session_id`
- Pronouns ("that", "it", "them") resolved from context
- Session messages stored in database, loaded on each request
- **Critical**: You must provide `--session-id` on every call to maintain continuity

---

## Step 3: Generate User Model from Activity

REM can create a user profile by analyzing files and conversations.

### 3.1 Upload More Files (Build Context)

```bash
# Process multiple files
rem process ingest resume.pdf --user-id user-123
rem process ingest meeting-notes.txt --user-id user-123
rem process ingest project-spec.md --user-id user-123
```

### 3.2 Have More Conversations

```bash
rem ask "I'm interested in distributed systems" --user-id user-123 --session-id profile-session
rem ask "What are the best practices for API design?" --user-id user-123 --session-id profile-session
rem ask "Tell me about PostgreSQL performance tuning" --user-id user-123 --session-id profile-session
```

### 3.3 Run User Model Dreaming

```bash
# Generate user model from recent activity
rem dreaming user-model --user-id user-123

# Check lookback window (default: 7 days)
rem dreaming user-model --user-id user-123 --lookback-hours 168
```

**What happens:**
1. Agent analyzes recent files + session messages
2. Extracts interests, skills, expertise level, communication style
3. Creates or updates `users` table entry for `user-123`
4. Stores structured profile in `properties` field

### 3.4 Query About User

```bash
# Ask about the user
rem ask "What are my interests?" --user-id user-123

# Ask about user's expertise
rem ask "What skills do I have based on my uploads?" --user-id user-123

# Ask about user's activity
rem ask "What have I been working on recently?" --user-id user-123
```

**What you'll see:**
- Agent uses `LOOKUP user-123 FROM users` to retrieve profile
- Answers based on extracted interests, skills, recent activity
- Combines user model + document context for personalized responses

---

## Step 4: Link Documents, Conversations, and User Profile

REM automatically creates connections between entities via graph edges.

### 4.1 Ask About Documents

```bash
# Query uploaded documents
rem ask "What documents have I uploaded?" --user-id user-123
```

**Behind the scenes:**
- Agent runs `SEARCH recent files FROM files WHERE user_id = 'user-123' ORDER BY created_at DESC LIMIT 10`
- Returns list of files with metadata

### 4.2 Ask Follow-Up About Specific Document

```bash
# First, get document name from previous answer
# Then ask follow-up
rem ask "Tell me more about resume.pdf" --user-id user-123
```

**Behind the scenes:**
- Agent runs `FUZZY "resume.pdf" FROM files` to find file
- Then runs `SEARCH FROM resources WHERE file_id = '{file_id}'` to get chunks
- Synthesizes answer from resource chunks

### 4.3 Ask About Conversations

```bash
# Query past conversations
rem ask "What have we discussed recently?" --user-id user-123
```

**Behind the scenes:**
- Agent queries `session_messages` table for recent conversations
- Summarizes topics discussed across sessions

### 4.4 Connect User Profile to Documents

```bash
# Ask how documents relate to user
rem ask "Which documents are most relevant to my interests?" --user-id user-123
```

**Behind the scenes:**
1. Agent retrieves user model: `LOOKUP user-123 FROM users`
2. Gets user interests from profile
3. Semantic search: `SEARCH interests-text FROM resources`
4. Ranks documents by relevance to user interests

---

## Step 5: REM Query Examples

Let's explore the REM query dialect directly.

### 5.1 LOOKUP - O(1) Entity Retrieval

```bash
# Direct lookup by label (if user model exists)
rem ask 'Run REM query: LOOKUP "user-123" FROM users' --user-id user-123

# Lookup specific resource by label
rem ask 'Run REM query: LOOKUP "project-spec" FROM resources' --user-id user-123
```

**Performance**: O(1) using KV store cache

### 5.2 FUZZY - Typo-Tolerant Search

```bash
# Find document with typo
rem ask 'Run REM query: FUZZY "resme.pdf" FROM files' --user-id user-123

# Partial filename match
rem ask 'Run REM query: FUZZY "meet" FROM files LIMIT 5' --user-id user-123
```

**Performance**: O(n) with pg_trgm GIN index (fast for small-medium datasets)

### 5.3 SEARCH - Semantic Vector Search

```bash
# Semantic search across resources
rem ask 'Run REM query: SEARCH "machine learning best practices" FROM resources LIMIT 10' --user-id user-123

# Search files by content
rem ask 'Run REM query: SEARCH "distributed systems" FROM files LIMIT 5' --user-id user-123
```

**Performance**: O(log n) with pgvector HNSW index

### 5.4 Direct Question (Agent Chooses Query)

```bash
# Let agent decide best query strategy
rem ask "What files did I upload recently?" --user-id user-123

# Agent might use: SEARCH recent files FROM files ORDER BY created_at DESC
```

---

## Step 6: Temporal Analysis with Moments

Moments classify resources into time-bound narratives.

### 6.1 Generate Moments

```bash
# Run moments dreaming
rem dreaming moments --user-id user-123

# Check progress
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT id, moment_type, start_time, end_time, summary
   FROM moments
   WHERE user_id = 'user-123'
   LIMIT 5;"
```

**What happens:**
1. Agent groups resources by temporal proximity (15-minute windows by default)
2. Classifies activity: "document_upload", "chat_session", "research_session"
3. Extracts: present_persons, speakers, emotion_tags, topic_tags
4. Creates moment narratives with start/end timestamps

### 6.2 Query Recent Activity

```bash
# Ask about recent activity
rem ask "What was I doing in the last hour?" --user-id user-123

# Ask about specific time period
rem ask "What activities happened yesterday afternoon?" --user-id user-123
```

**Behind the scenes:**
- Agent uses `SQL` query mode for temporal filtering
- Queries moments table with time range predicates
- Returns chronological activity summary

### 6.3 Query Activity Patterns

```bash
# Ask about patterns
rem ask "What time of day am I most active?" --user-id user-123

# Ask about topics over time
rem ask "How have my topics of interest changed over the past week?" --user-id user-123
```

**Behind the scenes:**
- Agent queries moments + resources with temporal grouping
- Analyzes topic tags distribution over time windows

---

## Step 7: Build Knowledge Graph with Affinity

Resource affinity creates semantic links between similar content.

### 7.1 Upload Similar Documents

```bash
# Upload related documents
rem process ingest ml-paper-1.pdf --user-id user-123
rem process ingest ml-paper-2.pdf --user-id user-123
rem process ingest ml-tutorial.md --user-id user-123
```

### 7.2 Run Affinity Dreaming

```bash
# Build semantic relationships
rem dreaming affinity --user-id user-123

# Check graph edges
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT id, category,
   jsonb_array_length(graph_edges) as edge_count,
   graph_edges
   FROM resources
   WHERE user_id = 'user-123'
   AND jsonb_array_length(graph_edges) > 0
   LIMIT 3;"
```

**What happens:**
1. Agent computes cosine similarity between resource embeddings
2. Creates `InlineEdge` objects for highly similar resources (threshold: 0.8)
3. Stores edges in `graph_edges` JSONB column:
   ```json
   [
     {
       "dst": "ml-paper-2-chunk-1",
       "rel_type": "similar_to",
       "weight": 0.92,
       "properties": {
         "dst_entity_type": "resources:ml-papers",
         "similarity_score": 0.92
       }
     }
   ]
   ```

### 7.3 Query Using Graph Traversal

```bash
# Find documents similar to a specific one
rem ask "What documents are similar to ml-paper-1.pdf?" --user-id user-123
```

**Behind the scenes:**
- Agent uses `LOOKUP "ml-paper-1" FROM files` to find file
- Then uses `TRAVERSE similar_to WITH LOOKUP "ml-paper-1" DEPTH 2`
- Returns connected resources via graph edges

### 7.4 Multi-Hop Traversal

```bash
# Find documents connected through intermediate nodes
rem ask "Show me a knowledge map of all ML-related documents" --user-id user-123
```

**Behind the scenes:**
- Agent uses `TRAVERSE` with depth 3-4 to explore graph
- Follows `similar_to`, `references`, `authored_by` edges
- Constructs knowledge graph visualization

### 7.5 Verify Graph Structure

```bash
# Visualize edge types
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT
     jsonb_path_query(graph_edges, '$[*].rel_type') as edge_type,
     COUNT(*) as count
   FROM resources
   WHERE user_id = 'user-123'
   GROUP BY edge_type;"

# Check edge weights distribution
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT
     jsonb_path_query(graph_edges, '$[*].weight')::float as weight,
     COUNT(*) as count
   FROM resources
   WHERE user_id = 'user-123'
   GROUP BY weight
   ORDER BY weight DESC;"
```

---

## Step 8: Complete Dreaming Workflow

Run all dreaming operations in sequence.

### 8.1 Full Dreaming Pipeline

```bash
# Run complete workflow: entities → moments → affinity → user model
rem dreaming full --user-id user-123

# With lookback window
rem dreaming full --user-id user-123 --lookback-hours 168 --limit 100
```

**What runs:**
1. **Entity Extraction**: Extract structured entities from resources
2. **Moment Generation**: Classify temporal activity windows
3. **Affinity Matching**: Build semantic graph edges
4. **User Model**: Update user profile from recent activity

### 8.2 Monitor Progress

```bash
# Check dreaming status
psql postgresql://rem:rem@localhost:5050/rem -c \
  "SELECT
     'resources' as entity_type, COUNT(*) as total,
     SUM(CASE WHEN processing_status = 'completed' THEN 1 ELSE 0 END) as completed
   FROM resources WHERE user_id = 'user-123'
   UNION ALL
   SELECT
     'moments' as entity_type, COUNT(*) as total, COUNT(*) as completed
   FROM moments WHERE user_id = 'user-123'
   UNION ALL
   SELECT
     'files' as entity_type, COUNT(*) as total,
     SUM(CASE WHEN processing_status = 'completed' THEN 1 ELSE 0 END) as completed
   FROM files WHERE user_id = 'user-123';"
```

### 8.3 Answerable Query Evolution

As dreaming progresses, more queries become answerable:

| Stage | Progress | Answerable Queries | Example |
|-------|----------|-------------------|---------|
| **Stage 0** | 0% | Raw resources only | "Search for 'machine learning' in my documents" |
| **Stage 1** | 20% | LOOKUP works | "What is project-spec?" |
| **Stage 2** | 50% | Temporal queries work | "What was I doing yesterday?" |
| **Stage 3** | 80% | Semantic + graph queries | "What documents are similar to my ML papers?" |
| **Stage 4** | 100% | Full query capabilities | "How have my interests evolved over time?" |

### 8.4 Test Query Capabilities

```bash
# Stage 0: Raw search (works immediately after ingestion)
rem ask "Search my documents for 'distributed systems'" --user-id user-123

# Stage 1: Entity lookups (after entity extraction)
rem ask "What is the document called 'project-spec'?" --user-id user-123

# Stage 2: Temporal queries (after moments dreaming)
rem ask "What documents did I upload this week?" --user-id user-123

# Stage 3: Graph traversal (after affinity matching)
rem ask "Show me documents related to my ML research" --user-id user-123

# Stage 4: Complex queries (after full dreaming)
rem ask "Compare my recent activity to my earlier work and show how my focus has shifted" --user-id user-123
```

---

## Step 9: Staged Query Generation (Advanced)

For complex requirements, you can preview the generated REM query before execution. This "staged" approach allows you to verify the logic before running it against the database.

We recommend using **Cerebras** (e.g., `cerebras:llama3.1-70b`) for this task due to its speed and reasoning capabilities.

### 9.1 Generate a Query Plan

Use the `--plan` flag to see the REM query without executing it.

```bash
# Generate plan for a complex question
rem ask "Find all documents about machine learning from last week that mention 'neural networks'" \
  --user-id user-123 \
  --agent-schema rem-query-agent \
  --model cerebras:llama3.1-70b \
  --plan
```

**Output (Plan):**
```sql
SEARCH "neural networks" FROM resources WHERE created_at > NOW() - INTERVAL '7 days' AND tags @> ARRAY['machine learning']
```

### 9.2 Execute the Staged Query

Copy the generated query and execute it directly using the `rem ask` command.

```bash
# Execute the generated query
rem ask 'Run REM query: SEARCH "neural networks" FROM resources WHERE created_at > NOW() - INTERVAL "7 days" AND tags @> ARRAY["machine learning"]' --user-id user-123
```

**Why use this flow?**
1.  **Verification**: Ensure the agent understands your intent before running expensive queries.
2.  **Learning**: See how natural language maps to the [REM Query Dialect](README.md#rem-query-dialect).
3.  **Tuning**: Manually tweak the query (e.g., change the time interval) before execution.

---

## Summary: The REM Journey

You've just experienced REM's **progressive memory enrichment**:

1. **Ingestion** (Step 1): Raw files → Chunks + Embeddings
2. **Retrieval** (Step 2): Semantic search + Sessions
3. **User Profiling** (Step 3): Activity → User model
4. **Entity Linking** (Step 4): Documents ↔ Conversations ↔ User
5. **Query Language** (Step 5): LOOKUP, FUZZY, SEARCH, TRAVERSE, SQL
6. **Temporal Analysis** (Step 6): Time-bound narratives
7. **Knowledge Graph** (Step 7): Semantic relationships
8. **Complete Workflow** (Step 8): 0% → 100% answerable
9. **Staged Queries** (Step 9): Plan → Verify → Execute

### Key Takeaways

- **Multi-Index Database**: KV store (O(1)), Vector (semantic), Graph (relationships), Time (temporal)
- **Progressive Enrichment**: Background dreaming workers continuously improve answerability
- **Query Flexibility**: 5 query types for different retrieval patterns
- **Session Continuity**: Follow-up questions work across CLI and API
- **Graph-Powered Reasoning**: Traverse semantic relationships for deep insights
- **Temporal Intelligence**: Understand activity patterns and evolution

### Next Steps

- Explore [rem/README.md](rem/README.md) for full API documentation
- Read [CLAUDE.md](CLAUDE.md) for design patterns and development guide
- Check [rem/src/rem/services/postgres/README.md](rem/src/rem/services/postgres/README.md) for database details
- See [rem/src/rem/services/phoenix/README.md](rem/src/rem/services/phoenix/README.md) for evaluation framework
- Check OTel traces sent to Phoenix (if configured) and begin your Evals and Agent calibration journey

### Getting Help

```bash
# CLI help
rem --help
rem <command> --help

# GitHub issues
https://github.com/mr-saoirse/remstack/issues

# Documentation
https://github.com/mr-saoirse/remstack
```

Happy querying!
