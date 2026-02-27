"""
Drop-in replacement for gemini_wrapper (LlmChat, UserMessage, ImageContent).
Uses the official google-genai SDK directly.
"""

import asyncio
import base64
from typing import List, Optional, Tuple

from google import genai


class ImageContent:
    """Wraps a base64-encoded image for inclusion in a message."""

    def __init__(self, image_base64: str):
        self.image_base64 = image_base64

    def _decode_image(self) -> Tuple[bytes, str]:
        """Decode base64 image and return (bytes, mime_type)."""
        b64 = self.image_base64
        mime_type = "image/png"

        if b64.startswith("data:"):
            header, b64 = b64.split(",", 1)
            if ";" in header:
                mime_type = header[5:].split(";")[0] or mime_type

        raw = base64.b64decode(b64)
        if mime_type == "image/png":
            # Heuristic fallback when mime type is not provided.
            if raw.startswith(b"\xff\xd8\xff"):
                mime_type = "image/jpeg"
            elif raw.startswith(b"RIFF") and b"WEBP" in raw[:16]:
                mime_type = "image/webp"

        return raw, mime_type

    def to_genai_part(self):
        """Convert to google-genai Part."""
        raw, mime_type = self._decode_image()
        return genai.types.Part.from_bytes(data=raw, mime_type=mime_type)


class UserMessage:
    """Combines text and optional image contents into a single message."""

    def __init__(self, text: str = "", file_contents: Optional[List[ImageContent]] = None):
        self.text = text
        self.file_contents = file_contents or []

    def to_genai_parts(self) -> list:
        """Convert to a list of parts for the google-genai SDK."""
        parts = []
        for img in self.file_contents:
            parts.append(img.to_genai_part())
        if self.text:
            parts.append(genai.types.Part.from_text(text=self.text))
        return parts


class LlmChat:
    """
    Drop-in replacement for gemini_wrapper.LlmChat.

    Supports the chaining API:
        chat = LlmChat(api_key=..., session_id=..., system_message=...)
            .with_model("gemini", "gemini-2.5-flash")
            .with_params(temperature=0)

    send_message() is async and returns a plain string.
    """

    def __init__(self, api_key: str = "", session_id: str = "", system_message: str = ""):
        self._api_key = api_key
        self._session_id = session_id
        self._system_message = system_message
        self._model_name = "gemini-2.5-flash"
        self._temperature = None
        self._extra_params = {}
        self._client = None
        self._chat = None  # lazily created

    def with_model(self, provider: str, model_name: str) -> "LlmChat":
        """Set the model. Provider is ignored (always Gemini)."""
        self._model_name = model_name
        return self

    def with_params(self, temperature: float = None, **kwargs) -> "LlmChat":
        """Set generation parameters."""
        if temperature is not None:
            self._temperature = temperature
        if kwargs:
            for key, value in kwargs.items():
                if value is not None:
                    self._extra_params[key] = value
        return self

    def _ensure_chat(self):
        """Lazily create the underlying google-genai chat session."""
        if self._chat is None:
            if not self._api_key:
                raise ValueError("Missing Gemini API key")

            gen_config = {}
            if self._temperature is not None:
                gen_config["temperature"] = self._temperature
            # Allow a bounded set of generation params used by callers.
            allowed_keys = {
                "top_p",
                "top_k",
                "candidate_count",
                "max_output_tokens",
                "stop_sequences",
                "response_mime_type",
                "response_schema",
                "seed",
                "presence_penalty",
                "frequency_penalty",
            }
            for key, value in self._extra_params.items():
                if key in allowed_keys and value is not None:
                    gen_config[key] = value
            if self._system_message:
                gen_config["system_instruction"] = self._system_message

            config = (
                genai.types.GenerateContentConfig(**gen_config)
                if gen_config
                else None
            )
            self._client = genai.Client(api_key=self._api_key)
            self._chat = self._client.chats.create(
                model=self._model_name,
                config=config,
                history=[],
            )

    async def send_message(self, message: UserMessage) -> str:
        """
        Send a message and return the response text as a plain string.

        This is async and uses run_in_executor for the synchronous SDK call.
        """
        self._ensure_chat()
        parts = message.to_genai_parts()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._chat.send_message(parts)
        )

        return response.text or ""
