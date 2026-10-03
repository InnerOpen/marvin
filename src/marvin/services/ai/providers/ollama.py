"""Ollama provider — calls the local Ollama REST API via httpx."""

import json

import httpx

from ..base import (
    AIProvider,
    CompletionOptions,
    CompletionResult,
    ImagePart,
    Message,
    ToolCall,
    ToolDefinition,
)


class OllamaProvider(AIProvider):
    provider_type = "ollama"
    display_name = "Ollama"
    supports_vision = False
    supports_structured_output = True
    supports_embeddings = True
    # Provider CAN pass tools to /api/chat; whether a call actually yields tool_calls depends on
    # the loaded model (llama3.1+, qwen2.5, …). The agent loop still gates on model support.
    supports_tool_calls = True
    # Ollama can download models on demand via /api/pull.
    supports_model_pull = True

    def __init__(self, base_url: str = "http://localhost:11434", api_key: str | None = None) -> None:
        # Ollama's REST API lives at {host}/api/*. We append "/api/..." to the base ourselves, so the
        # base must be the host root. Tolerate a base that already includes a trailing "/api" (a
        # common misconfig, e.g. OLLAMA_BASE_URL=http://host:11434/api) instead of doubling it into
        # ".../api/api/tags".
        base = base_url.rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        self._base_url = base
        # api_key unused for local Ollama but kept for interface consistency

    def _to_api_messages(self, messages: list[Message]) -> list[dict]:
        """Ollama carries images in a separate `images` list (base64) alongside text content."""
        out: list[dict] = []
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
                continue
            text = " ".join(str(p) for p in m.content if not isinstance(p, ImagePart))
            images = [p.data for p in m.content if isinstance(p, ImagePart)]
            msg: dict = {"role": m.role, "content": text}
            if images:
                msg["images"] = images
            out.append(msg)
        return out

    def _to_api_tool_messages(self, messages: list[Message]) -> list[dict]:
        """Render the tool-calling round-trip into Ollama's native /api/chat shape.

        Ollama carries tool calls as `message.tool_calls[].function.{name,arguments}` (arguments an
        OBJECT, not a JSON string) and tool results as plain role="tool" messages — no call id.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == "tool":
                content = m.content if isinstance(m.content, str) else str(m.content)
                out.append({"role": "tool", "content": content})
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content if isinstance(m.content, str) else "",
                        "tool_calls": [{"function": {"name": tc.name, "arguments": tc.arguments}} for tc in m.tool_calls],
                    }
                )
            else:
                out.extend(self._to_api_messages([m]))
        return out

    def _chat(
        self,
        model: str,
        messages: list[dict],
        options: CompletionOptions,
        fmt: dict | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"model": model, "messages": messages, "stream": False}
        if fmt:
            payload["format"] = fmt
        if tools:
            payload["tools"] = tools
        if options.temperature is not None:
            payload.setdefault("options", {})["temperature"] = options.temperature
        resp = httpx.post(f"{self._base_url}/api/chat", json=payload, timeout=120)
        if resp.status_code >= 400:
            raise self._error(resp, model, bool(tools))
        return resp.json()

    @staticmethod
    def _error(resp: httpx.Response, model: str, had_tools: bool) -> Exception:
        """Turn Ollama's terse error body into an actionable message (raise_for_status hides it).

        The common one: a text-only model (gemma, phi, …) asked to tool-call — Ollama returns
        HTTP 400 `"<model> does not support tools"`, which surfaces to the user as a bare
        "400 Bad Request". Point them at a tool-capable model instead.
        """
        try:
            detail = (resp.json().get("error") or "").strip() or resp.text.strip()
        except Exception:
            detail = resp.text.strip()
        if resp.status_code == 400 and had_tools and "does not support tools" in detail.lower():
            return RuntimeError(
                f"The Ollama model '{model}' can't use tools, which the agent requires. "
                f"Pick a tool-capable model (e.g. qwen3-coder, qwen2.5, llama3.1) as this workspace's "
                f"model — text-only models like gemma/phi still work for plain operations (summary, tags)."
            )
        return RuntimeError(f"Ollama /api/chat failed (HTTP {resp.status_code}): {detail or 'no detail'}")

    def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDefinition],
        options: CompletionOptions | None = None,
        tool_choice: str = "auto",
    ) -> CompletionResult:
        # Ollama's native API has no tool_choice; the model decides. `tool_choice` is accepted for
        # interface parity and ignored.
        opts = options or CompletionOptions()
        api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        data = self._chat(model, self._to_api_tool_messages(messages), opts, tools=api_tools)
        msg = data.get("message", {})

        tool_calls: list[ToolCall] = []
        for i, rc in enumerate(msg.get("tool_calls") or []):
            fn = rc.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            # Ollama does not return an id; synthesize a stable one for the round-trip.
            tool_calls.append(ToolCall(id=rc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))

        prompt_tokens, completion_tokens = data.get("prompt_eval_count", 0), data.get("eval_count", 0)
        return CompletionResult(
            content=msg.get("content", ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model,
            raw=data,
            tool_calls=tool_calls,
            stop_reason="tool_calls" if tool_calls else data.get("done_reason"),
        )

    def complete(self, messages: list[Message], model: str, options: CompletionOptions | None = None) -> CompletionResult:
        opts = options or CompletionOptions()
        data = self._chat(model, self._to_api_messages(messages), opts)
        msg = data.get("message", {})
        usage = data.get("prompt_eval_count", 0), data.get("eval_count", 0)
        return CompletionResult(
            content=msg.get("content", ""),
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            total_tokens=usage[0] + usage[1],
            model=model,
            raw=data,
        )

    def complete_structured(self, messages: list[Message], model: str, output_schema: dict, options: CompletionOptions | None = None) -> dict:
        opts = options or CompletionOptions()
        data = self._chat(model, self._to_api_messages(messages), opts, fmt=output_schema)
        content = data.get("message", {}).get("content", "{}")
        return json.loads(content)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            resp = httpx.post(f"{self._base_url}/api/embeddings", json={"model": model, "prompt": t}, timeout=60)
            if resp.status_code >= 400:
                raise self._embed_error(resp, model)
            out.append(resp.json()["embedding"])
        return out

    @staticmethod
    def _embed_error(resp: httpx.Response, model: str) -> Exception:
        """Unwrap Ollama's embed error (raise_for_status hides it). The common one: the embedding
        model isn't pulled — Ollama returns 404 `"model ... not found, try pulling it first"`."""
        try:
            detail = (resp.json().get("error") or "").strip() or resp.text.strip()
        except Exception:
            detail = resp.text.strip()
        if "not found" in detail.lower():
            return RuntimeError(
                f"The Ollama embedding model '{model}' isn't pulled. Run `ollama pull {model}` "
                f"(embeddings power search/RAG). Or set OLLAMA_EMBEDDING_MODEL to an installed "
                f"embedding model (e.g. nomic-embed-text, mxbai-embed-large) — a chat model like "
                f"gemma3 can't embed."
            )
        return RuntimeError(f"Ollama embeddings failed (HTTP {resp.status_code}): {detail or 'no detail'}")

    def list_models(self) -> list[str]:
        resp = httpx.get(f"{self._base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    def pull_model(self, name: str, on_progress=None) -> None:
        """Download `name` via Ollama's streaming /api/pull, forwarding progress line by line.

        Ollama streams NDJSON: `{"status": "...", "completed": N, "total": M}` while pulling layers,
        ending with `{"status": "success"}`. A `{"error": "..."}` line means the pull failed
        (e.g. no such model in the registry) — we raise so the caller marks the job failed.
        """
        with httpx.stream("POST", f"{self._base_url}/api/pull", json={"model": name, "stream": True}, timeout=None) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    update = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if update.get("error"):
                    raise RuntimeError(update["error"])
                if on_progress:
                    on_progress(update)

    def test_connection(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
            return True, f"Connected — {len(models)} models available"
        except Exception as e:
            return False, str(e)
