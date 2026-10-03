"""System-defined AI operations — available to all workspaces."""

from ..base import ImagePart, Message
from .base import ROLE_AUTHOR, ROLE_EDITOR, AIOperation, OperationContext, register_operation


@register_operation
class GenerateSummaryOperation(AIOperation):
    slug = "generate-summary"
    name = "Generate Summary"
    description = "Summarise entry or resource content into a concise paragraph."
    entity_types = ["entry", "resource"]
    min_role = ROLE_AUTHOR
    input_schema = {
        "type": "object",
        "properties": {
            "max_words": {"type": "integer", "default": 80},
            "focus": {"type": "string", "description": "Optional topic to focus the summary on"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "word_count": {"type": "integer"},
        },
        "required": ["summary", "word_count"],
    }
    writeback = {"summary": "summary"}

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        max_words = input.get("max_words", 80)
        focus = input.get("focus", "")
        content = ctx.entry.get("content", "") if ctx.entry else ""
        title = ctx.entry.get("title", "") if ctx.entry else ""
        focus_clause = f" Focus on: {focus}." if focus else ""
        return [
            Message(role="system", content=(f"You are a content assistant for {ctx.workspace_name or 'this workspace'}. Locale: {ctx.site_locale}.")),
            Message(
                role="user",
                content=(
                    f"Summarise the following content in no more than {max_words} words.{focus_clause}\n\n"
                    f"Title: {title}\n\nContent:\n{content}\n\n"
                    f'Return JSON: {{"summary": "...", "word_count": <int>}}'
                ),
            ),
        ]


@register_operation
class GenerateTagsOperation(AIOperation):
    slug = "generate-tags"
    name = "Generate Tags"
    description = (
        "Suggest relevant tags or keywords for one entry, asset (from the image itself) or resource, reusing `vocabulary` tags only where they fit."
    )
    entity_types = ["entry", "resource", "asset"]
    min_role = ROLE_AUTHOR
    # An image asset is tagged from the picture itself, not just its filename.
    sees_asset_image = True
    input_schema = {
        "type": "object",
        "properties": {
            "max_tags": {"type": "integer", "default": 8},
            "existing_tags": {"type": "array", "items": {"type": "string"}},
            "vocabulary": {
                "type": "array",
                "items": {"type": "string"},
                "description": "the workspace's existing tag names: reused where they genuinely fit this item, never applied wholesale",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["tags"],
    }
    # Write onto the real tag vocabulary: the "tags" target find-or-creates each suggested name
    # (group-scoped, by slug) and links it, unioning with the entry's existing tags. See
    # EntriesRepository.apply_fields.
    writeback = {"tags": "tags"}

    @staticmethod
    def _subject(ctx: OperationContext) -> tuple[str, dict | None]:
        """(what is being tagged, as text; the image asset when its pixels are loaded). An entry is
        its title + content; an asset or resource — with no entry in context — its own fields."""
        if ctx.entry:
            return f"Title: {ctx.entry.get('title', '')}\nContent:\n{ctx.entry.get('content', '')}", None
        if ctx.assets:
            asset = ctx.assets[0]
            lines = [f"Asset: {asset.get('name', '')}"]
            lines += [f"{label}: {asset[key]}" for key, label in (("alt_text", "Alt text"), ("description", "Description")) if asset.get(key)]
            return "\n".join(lines), (asset if asset.get("image_data") else None)
        if ctx.resources:
            res = ctx.resources[0]
            return f"Resource: {res.get('name', '')} ({res.get('type', '')})\nDescription: {res.get('description', '')}", None
        return "", None

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        max_tags = input.get("max_tags", 8)
        existing = input.get("existing_tags", [])
        vocabulary = input.get("vocabulary", [])
        existing_clause = f"Existing tags (do not repeat): {', '.join(existing)}." if existing else ""
        vocabulary_clause = (
            f"Workspace tags you may reuse — only the ones that genuinely fit this item, never the whole list: {', '.join(vocabulary)}."
            if vocabulary
            else ""
        )
        subject, image_asset = self._subject(ctx)
        look = "Base the tags on what the image actually shows. " if image_asset else ""
        instruction = (
            f"Suggest up to {max_tags} relevant tags for this item. {look}{existing_clause} {vocabulary_clause}\n\n"
            f"{subject}\n\n"
            f'Return JSON: {{"tags": ["tag1", "tag2"]}}'
        )
        user_content = (
            [instruction, ImagePart(data=image_asset["image_data"], mime_type=image_asset.get("mime_type") or "image/png")]
            if image_asset
            else instruction
        )
        return [
            Message(role="system", content=f"You are a tagging assistant for {ctx.workspace_name or 'this workspace'}."),
            Message(role="user", content=user_content),
        ]


@register_operation
class ImproveWritingOperation(AIOperation):
    slug = "improve-writing"
    name = "Improve Writing"
    description = "Improve clarity, grammar, and style of entry content."
    entity_types = ["entry"]
    min_role = ROLE_AUTHOR
    input_schema = {
        "type": "object",
        "properties": {
            "tone": {"type": "string", "description": "Desired tone override (e.g. formal, casual)"},
            "text": {
                "type": "string",
                "description": (
                    "The prose to improve. Strongly preferred: without it this falls back to the "
                    "entry's serialized data_json, which is a structured blob, not prose."
                ),
            },
            "field": {
                "type": "string",
                "description": "Label of the field `text` came from — echoed back so callers can route the result.",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "improved": {"type": "string"},
            "changes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["improved", "changes"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        tone = input.get("tone") or ctx.variables.get("AI_TONE", "professional")
        # Prefer caller-supplied prose. ctx.entry["content"] is str(data_json) — a structured
        # blob — so improving it produces text with nowhere sensible to go. The fallback is kept
        # only so existing API/MCP callers don't break.
        content = (input.get("text") or "").strip()
        if not content:
            content = ctx.entry.get("content", "") if ctx.entry else ""
        return [
            Message(
                role="system",
                content=(f"You are a writing assistant for {ctx.workspace_name or 'this workspace'}. Tone: {tone}. Locale: {ctx.site_locale}."),
            ),
            Message(
                role="user",
                content=(
                    f"Improve the following content for clarity, grammar, and style. "
                    f"Preserve meaning and structure.\n\nContent:\n{content}\n\n"
                    f'Return JSON: {{"improved": "...", "changes": ["description of change"]}}'
                ),
            ),
        ]


@register_operation
class GenerateAltTextOperation(AIOperation):
    slug = "generate-alt-text"
    name = "Generate Alt Text"
    description = "Generate accessible alt text for an image asset."
    entity_types = ["asset"]
    requires_vision = True
    min_role = ROLE_AUTHOR
    input_schema = {
        "type": "object",
        "properties": {
            "context": {"type": "string", "description": "Optional context about where the image is used"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "alt_text": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["alt_text"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        usage_context = input.get("context", "")
        context_clause = f"Context: {usage_context}." if usage_context else ""
        asset = ctx.assets[0] if ctx.assets else {}
        filename = asset.get("name", "this image")
        instruction = (
            f"Write alt text for the image '{filename}'. {context_clause} "
            f"Alt text should be under 125 characters and describe what is shown.\n\n"
            f'Return JSON: {{"alt_text": "...", "description": "longer description"}}'
        )
        image_data = asset.get("image_data")
        user_content = [instruction, ImagePart(data=image_data, mime_type=asset.get("mime_type") or "image/png")] if image_data else instruction
        return [
            Message(
                role="system", content="You are an accessibility assistant. Write concise, descriptive alt text based on what you see in the image."
            ),
            Message(role="user", content=user_content),
        ]


@register_operation
class ClassifyFormSubmissionOperation(AIOperation):
    slug = "classify-form-submission"
    name = "Classify Form Submission"
    description = "Classify a form submission by category, detect spam, and extract sentiment."
    entity_types = ["form_submission"]
    min_role = ROLE_EDITOR
    input_schema = {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Possible categories to classify into",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "confidence": {"type": "number"},
            "is_spam": {"type": "boolean"},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "action_required": {"type": "boolean"},
        },
        "required": ["category", "confidence", "is_spam", "sentiment", "action_required"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        categories = input.get("categories", ["inquiry", "support", "feedback", "other"])
        submission = ctx.form_submission or {}
        data = submission.get("data", {})
        return [
            Message(role="system", content=(f"You are a form submission classifier for {ctx.workspace_name or 'this workspace'}.")),
            Message(
                role="user",
                content=(
                    f"Classify this form submission.\n\nSubmission data:\n{data}\n\n"
                    f"Available categories: {', '.join(categories)}.\n\n"
                    f"Return JSON matching the output schema."
                ),
            ),
        ]


@register_operation
class DescribeImageOperation(AIOperation):
    slug = "describe-image"
    name = "Describe Image"
    description = "Produce a detailed description of an image asset, with detected objects and colors."
    entity_types = ["asset"]
    requires_vision = True
    min_role = ROLE_AUTHOR
    input_schema = {"type": "object", "properties": {}}
    output_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "detected_objects": {"type": "array", "items": {"type": "string"}},
            "colors": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["description"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        asset = ctx.assets[0] if ctx.assets else {}
        filename = asset.get("name", "this image")
        instruction = (
            f"Describe the image '{filename}' in detail. List the main objects you see and the "
            f"dominant colours.\n\n"
            f'Return JSON: {{"description": "...", "detected_objects": ["..."], "colors": ["..."]}}'
        )
        image_data = asset.get("image_data")
        user_content = [instruction, ImagePart(data=image_data, mime_type=asset.get("mime_type") or "image/png")] if image_data else instruction
        return [
            Message(role="system", content="You are a vision assistant. Describe images accurately based on what you see."),
            Message(role="user", content=user_content),
        ]


@register_operation
class EnrichResourceMetadataOperation(AIOperation):
    slug = "enrich-resource-metadata"
    name = "Enrich Resource Metadata"
    description = "Suggest a description, tags, and category for a resource from its name and URL."
    entity_types = ["resource"]
    min_role = ROLE_AUTHOR
    input_schema = {"type": "object", "properties": {}}
    output_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "category": {"type": "string"},
        },
        "required": ["description"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        resource = ctx.resources[0] if ctx.resources else {}
        name = resource.get("name", "")
        rtype = resource.get("type", "")
        url = resource.get("url", "")
        existing = resource.get("description", "")
        return [
            Message(role="system", content=(f"You are a metadata assistant for {ctx.workspace_name or 'this workspace'}.")),
            Message(
                role="user",
                content=(
                    f"Enrich metadata for this resource.\n\n"
                    f"Name: {name}\nType: {rtype}\nURL: {url}\nExisting description: {existing or '(none)'}\n\n"
                    f'Return JSON: {{"description": "...", "tags": ["..."], "category": "..."}}'
                ),
            ),
        ]


@register_operation
class AnswerWorkspaceQuestionOperation(AIOperation):
    slug = "answer-workspace-question"
    name = "Answer Workspace Question"
    description = "Answer a question using semantically-retrieved workspace content, with citations."
    entity_types = []
    requires_retrieval = True
    min_role = ROLE_AUTHOR
    input_schema = {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer"],
    }

    def build_prompt(self, input: dict, ctx: OperationContext) -> list[Message]:
        question = input.get("question", "")
        chunks = ctx.retrieved or []
        context_block = (
            "\n\n".join(f"[{i + 1}] ({c['entity_type']} {c['entity_id']}): {c['text']}" for i, c in enumerate(chunks))
            or "(no relevant workspace content found)"
        )
        return [
            Message(
                role="system",
                content=(
                    f"You are a knowledge assistant for {ctx.workspace_name or 'this workspace'}. "
                    f"Answer the question using ONLY the provided context. Cite sources by their [n] "
                    f"index. If the context does not contain the answer, say you don't know."
                ),
            ),
            Message(
                role="user", content=(f'Question: {question}\n\nContext:\n{context_block}\n\nReturn JSON: {{"answer": "...", "sources": ["[1]"]}}')
            ),
        ]
