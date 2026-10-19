# AI Intake (Future Phase)

This document outlines the planned AI-assisted content intake system for Marvin. This is a future phase and should NOT be implemented in the initial platform sprint.

## Overview

The AI intake system will accelerate entry creation by:

1. Converting voice notes to structured entries
2. Processing image uploads with OCR and analysis
3. Generating draft entries with AI assistance
4. Suggesting metadata (titles, summaries, tags, collections)
5. Requiring human review before publishing

## Voice Intake

### Workflow

```
User records voice note → Stored in assets table → AI transcription + processing → Draft entry created → Human review → Publish
```

### Implementation Details

- Transcribe audio using OpenAI Whisper or similar
- Extract key information (dates, entities, actions)
- Detect entry type from content (bench note, guide, procedure, etc)
- Generate initial structure (heading hierarchy, sections)
- Create entry in `draft` status
- Notify group admin of draft for review

### UI Flow

1. User clicks "Record note" in admin UI
2. Browser records voice via Web Audio API
3. Audio blob uploaded to `/api/admin/assets` with `purpose: voice_intake`
4. Backend processes asynchronously
5. System creates draft entry with `content_source: voice`
6. Draft appears in admin review queue

## Image Intake

### Workflow

```
User uploads image → Stored in assets table → AI analysis + OCR → Draft entry or entry enhancement → Human review
```

### Implementation Details

- Accept images (JPG, PNG, WebP)
- Run OCR to extract text (Google Cloud Vision, Azure, local Tesseract)
- Analyze image metadata (colors, objects, composition)
- If form/document: extract structured data
- If reference material: create entry with caption and OCR text
- Store AI analysis in `assets.metadata.ai_analysis` JSON

### UI Flow

1. User drags image into admin UI
2. Image uploaded to `/api/admin/assets` with `purpose: image_intake`
3. Backend processes asynchronously (may take minutes)
4. If OCR'd text detected: create entry draft
5. If just metadata: enhance existing entry with metadata
6. User reviews and publishes

## AI-Generated Drafts

### Suggested Metadata

For each draft entry, AI suggests:

- **Title**: `entries.title` with confidence score
- **Summary**: `entries.summary` with suggested alternatives
- **Entry Type**: `entries.entry_type` with confidence
- **Tags/Topics**: Freeform suggestions for categorization
- **Collections**: Suggest 2-3 collections to add entry to
- **Resources**: Suggest related resources already in system

### Metadata Suggestion Response

```json
{
  "entry_id": "uuid",
  "suggestions": {
    "title": {
      "primary": "How to Sew a Flat Felled Seam",
      "alternatives": [
        "The Flat Felled Seam Technique",
        "Flat Felled Seams for Durability"
      ],
      "confidence": 0.95
    },
    "summary": "A step-by-step guide to creating flat felled seams for added durability and a professional finish.",
    "entry_type": {
      "suggested": "procedure",
      "alternatives": ["guide", "reference"],
      "confidence": 0.88
    },
    "topics": ["sewing", "seams", "technique", "durability"],
    "collections": [
      {
        "id": "uuid",
        "name": "Sewing Techniques",
        "confidence": 0.92
      }
    ],
    "resources": [
      {
        "id": "uuid",
        "name": "Needle and Thread Set",
        "confidence": 0.45
      }
    ]
  }
}
```

## Admin Review Queue

### Workflow

Admins review and approve AI-generated drafts before publishing:

1. List drafts created by AI (`source: ai`)
2. Review AI suggestions
3. Accept/reject/modify suggestions
4. Edit entry content
5. Publish or send back for more context

### Entry Metadata

Add fields to track AI provenance:

```sql
entries
  ...
  source (enum: human, voice_intake, image_intake, ai_assisted)
  ai_processing_log (json, nullable)
  human_reviewed_at (nullable timestamp)
  human_reviewed_by (nullable foreign key to users)
```

## Processing Architecture

### Asynchronous Processing

Use Celery or APScheduler with a task queue:

```python
# marvin/services/ai_intake/voice_processor.py
@celery_app.task
def process_voice_note(asset_id: UUID):
    asset = get_asset(asset_id)
    transcript = transcribe_audio(asset.file_path)
    entry_draft = create_entry_from_transcript(transcript)
    return entry_draft.id

# Usage in route
@router.post("/assets")
def upload_asset(file: UploadFile):
    asset = store_asset(file)
    if file.headers.get("X-Purpose") == "voice_intake":
        process_voice_note.delay(asset.id)
    return asset
```

### Error Handling

- If transcription fails: Log error, notify admin, move to error queue
- If entry creation fails: Mark asset with error status, notify admin
- If suggestions fail: Return partial entry without suggestions

## AI Model Choices (Not Decided Yet)

- **Transcription**: OpenAI Whisper, Google Cloud Speech-to-Text, or local Silero
- **Text Analysis**: OpenAI GPT-4, Claude, or local open-source LLM
- **Image Analysis**: Google Cloud Vision, Azure Computer Vision, or local YOLO
- **Embeddings**: For semantic search and collection suggestions

Trade-offs:
- Cloud APIs: Fast, accurate, but cost and privacy considerations
- Local models: Privacy-friendly, free, but slower and less accurate
- Hybrid: Use cloud for primary, local for fallback

## Security Considerations

- AI processing should never expose confidential data outside workspace
- Transcription and image analysis should happen server-side, not client-side
- If using cloud APIs, verify they don't train on data
- Rate-limit AI intake to prevent abuse
- Log all AI-generated content for audit trail

## Future Extensions

1. **Recurring Intake**: "Every voice note tagged #weekly should trigger procedure creation"
2. **Batch Processing**: Process 100 voice notes overnight
3. **Feedback Loop**: Track which AI suggestions users accept/reject to improve future suggestions
4. **Entity Recognition**: Automatically link extracted entities to existing resources
5. **Layout Detection**: For scanned documents, understand page layout and section structure

## Testing Strategy

- Mock AI services in unit tests
- Integration tests against sandbox endpoints
- Manual testing with real voice notes and images
- A/B test suggestion quality
- Measure admin time to review/approve

## Rollout Plan

1. **Beta**: Limited to one workspace, manual opt-in
2. **Alpha**: All workspaces, behind feature flag
3. **General Availability**: Default enabled, with opt-out
4. **Monitoring**: Track processing success rate, user satisfaction, cost
