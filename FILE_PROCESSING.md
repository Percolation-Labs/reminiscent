# File Processing System

Event-driven file processing using S3 → SQS → KEDA → K8s pattern.

## Architecture

```
User uploads file
       ↓
S3: s3://rem/uploads/document.md
       ↓ (S3 ObjectCreated event)
SQS: rem-file-processing queue
       ↓ (KEDA monitors queue depth)
K8s Deployment: file-processor (0-20 pods)
       ↓ (SQSFileProcessor worker)
ContentService.process_uri()
       ↓ (MarkdownProvider)
Extract text content
       ↓ (TODO: embedding generation)
PostgreSQL + pgvector
```

## Components

### 1. ContentService (`rem/src/rem/services/content/`)

Core service for file processing with pluggable providers.

**Features:**
- S3 URI support (`s3://bucket/key`)
- Local file support (`./path/to/file`)
- Provider plugins for different file types
- Extensible via `register_provider()`

**Currently Supported:**
- Markdown (`.md`, `.markdown`)

**Future Providers:**
- PDF extraction
- HTML parsing
- DOCX/document formats
- Image OCR

**Usage:**
```python
from rem.services.content import ContentService

service = ContentService()
result = service.process_uri("s3://rem/uploads/doc.md")

print(result["content"])  # Extracted text
print(result["metadata"])  # File metadata
print(result["provider"])  # "markdown"
```

### 2. CLI Command (`rem process uri`)

Command-line interface for testing content extraction.

**Usage:**
```bash
# Process local file
rem process uri ./README.md

# Process S3 file
rem process uri s3://rem/uploads/document.md

# Save to file
rem process uri s3://rem/uploads/doc.md -s output.json

# Text-only output
rem process uri ./file.md -o text
```

### 3. SQS Worker (`rem/src/rem/workers/sqs_file_processor.py`)

Background worker that consumes S3 events from SQS queue.

**Features:**
- Long polling (20s) for efficient SQS usage
- Graceful shutdown (SIGTERM/SIGINT)
- Batch processing (up to 10 messages)
- DLQ support (3 retries)
- IRSA authentication (no credentials in code)

**Deployment:**
- Runs as K8s Deployment
- Scaled 0-20 pods by KEDA based on queue depth
- Spot instances for cost optimization

**Entry point:**
```bash
python -m rem.workers.sqs_file_processor
```

### 4. K8s Deployment (`manifests/application/file-processor/`)

Production deployment with KEDA autoscaling.

**Key Files:**
- `deployment.yaml` - Pod spec with IRSA ServiceAccount
- `keda-scaledobject.yaml` - KEDA scaling config (1 pod per 10 messages)

**Scaling Example:**
- 0 messages → 0 pods (scale to zero)
- 25 messages → 3 pods
- 100 messages → 10 pods
- 250 messages → 20 pods (max)

## Configuration

### Environment Variables

```bash
# .env or K8s ConfigMap
SQS__QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/rem-file-processing
SQS__REGION=us-east-1
SQS__MAX_MESSAGES=10
SQS__WAIT_TIME_SECONDS=20
SQS__VISIBILITY_TIMEOUT=300

S3__BUCKET_NAME=rem
S3__REGION=us-east-1
```

### IRSA Permissions

Worker pods need two IAM roles:

1. **KEDA operator role** - Read SQS metrics
   ```
   sqs:GetQueueAttributes
   sqs:ListQueues
   ```

2. **File processor role** - Consume queue + read S3
   ```
   sqs:ReceiveMessage
   sqs:DeleteMessage
   sqs:ChangeMessageVisibility
   s3:GetObject
   ```

## Provider Plugin System

Add custom content providers for new file types:

```python
from rem.services.content import ContentService
from rem.services.content.providers import ContentProvider

class PDFProvider(ContentProvider):
    @property
    def name(self) -> str:
        return "pdf"

    def extract(self, content: bytes, metadata: dict) -> dict:
        # Use PyMuPDF, pdfplumber, etc.
        text = extract_text_from_pdf(content)
        return {"text": text, "metadata": {...}}

# Register provider
service = ContentService()
service.register_provider([".pdf"], PDFProvider())
```

## Local Development

### Test CLI locally

```bash
cd rem
uv pip install -e .

# Test with local file
echo "# Test Document" > test.md
rem process uri test.md

# Test with S3 (requires AWS credentials or IRSA)
aws s3 cp test.md s3://rem/uploads/
rem process uri s3://rem/uploads/test.md
```

### Test worker locally

```bash
# Set environment variables
export SQS__QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/rem-file-processing
export SQS__REGION=us-east-1
export S3__BUCKET_NAME=rem
export S3__REGION=us-east-1

# Run worker
python -m rem.workers.sqs_file_processor

# Upload test file (in another terminal)
aws s3 cp test.md s3://rem/uploads/

# Watch worker logs process the file
```

## Production Deployment

### 1. Build and push Docker image

```bash
cd rem
docker build -f Dockerfile.worker -t your-registry/rem:latest .
docker push your-registry/rem:latest
```

### 2. Deploy infrastructure (Pulumi)

```bash
cd ../manifests/infra/file-queue
pulumi up
# Note queue URL and IAM policy ARNs
```

### 3. Deploy KEDA platform

```bash
cd ../../platform/keda
kubectl apply -f application.yaml
```

### 4. Configure IRSA roles

```bash
# Annotate KEDA operator ServiceAccount
kubectl annotate sa keda-operator -n keda \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/keda-operator-role
```

### 5. Deploy file processor

```bash
cd ../../application/file-processor

# Update ACCOUNT_ID in deployment.yaml and keda-scaledobject.yaml
sed -i 's/ACCOUNT_ID/123456789012/g' *.yaml

kubectl apply -f .
```

### 6. Verify scaling

```bash
# Should start at 0 pods
kubectl get pods -l app=file-processor

# Upload test files
for i in {1..25}; do
  echo "test $i" | aws s3 cp - s3://rem/uploads/test-$i.md
done

# Watch scale up to 3 pods
kubectl get pods -l app=file-processor -w

# Watch HPA
kubectl get hpa file-processor-scaler -w
```

## Cost Optimization

- **Scale to zero**: No cost when idle
- **Spot instances**: 70-90% savings (configured in Deployment affinity)
- **Long polling**: Reduces SQS API calls
- **Batch processing**: Up to 10 messages per receive
- **KEDA efficiency**: Only scales when needed

**Monthly cost estimate** (us-east-1, assuming 10k files/day):
- SQS: ~$1 (requests + data transfer)
- S3 storage: ~$5 (100 GB)
- Compute: ~$10 (spot instances, avg 2 pods)
- **Total: ~$16/month**

## Future Enhancements

### Short Term
- [ ] PDF support (PyMuPDF/pdfplumber provider)
- [ ] PostgreSQL storage integration
- [ ] Embedding generation (OpenAI/local models)
- [ ] Graph edge creation

### Medium Term
- [ ] HTML/web page extraction
- [ ] DOCX/Office formats
- [ ] Image OCR (Tesseract/cloud OCR)
- [ ] Chunking strategies for large documents

### Long Term
- [ ] Video transcription
- [ ] Audio processing
- [ ] Custom ML model inference
- [ ] Multi-language support

## Monitoring

### CloudWatch Metrics

- **Queue depth**: `ApproximateNumberOfMessagesVisible`
- **Processing rate**: Messages per second
- **DLQ depth**: Failed messages
- **Pod count**: Kubernetes metrics

### Logs

```bash
# Worker logs
kubectl logs -l app=file-processor -f

# KEDA scaling events
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=100
```

### Alerts

- Queue depth > 100 for 5+ minutes (backlog)
- DLQ depth > 0 (processing failures)
- Pod crash loops (worker errors)

## Troubleshooting

### Pods not scaling

```bash
# Check ScaledObject
kubectl describe scaledobject file-processor-scaler

# Check KEDA logs
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50
```

### Access Denied errors

```bash
# Verify IRSA annotation
kubectl get sa file-processor -o yaml | grep role-arn

# Check pod environment
kubectl get pod -l app=file-processor -o yaml | grep -A5 env:
```

### Messages not being processed

```bash
# Check queue has messages
aws sqs get-queue-attributes \
  --queue-url QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages

# Check worker logs
kubectl logs -l app=file-processor --tail=100
```

## References

- Architecture: `/CLAUDE.md`
- Infrastructure: `manifests/infra/file-queue/README.md`
- KEDA: `manifests/platform/keda/README.md`
- Deployment: `manifests/application/file-processor/README.md`
