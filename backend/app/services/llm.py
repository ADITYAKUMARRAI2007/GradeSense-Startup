"""
Drop-in replacement for gemini_wrapper (LlmChat, UserMessage, ImageContent).
Uses the official google-generativeai SDK directly.
"""

import asyncio
import base64
import inspect
from typing import List, Optional

import google.generativeai as genai

from app.config import logger


class ImageContent:
    """Wraps a base64-encoded image for inclusion in a message."""

    def __init__(self, image_base64: str):
        self.image_base64 = image_base64

    def to_genai_part(self) -> dict:
        """Convert to google-generativeai inline_data format."""
        # Strip data URI prefix if present
        b64 = self.image_base64
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return {
            "inline_data": {
                "mime_type": "image/png",
                "data": b64,
            }
        }


class UserMessage:
    """Combines text and optional image contents into a single message."""

    def __init__(self, text: str = "", file_contents: Optional[List[ImageContent]] = None):
        self.text = text
        self.file_contents = file_contents or []

    def to_genai_parts(self) -> list:
        """Convert to a list of parts for the google-generativeai SDK."""
        parts = []
        for img in self.file_contents:
            parts.append(img.to_genai_part())
        if self.text:
            parts.append(self.text)
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
        self._chat = None  # lazily created

    def with_model(self, provider: str, model_name: str) -> "LlmChat":
        """Set the model. Provider is ignored (always Gemini)."""
        self._model_name = model_name
        return self

    def with_params(self, temperature: float = None, **kwargs) -> "LlmChat":
        """Set generation parameters."""
        if temperature is not None:
            self._temperature = temperature
        return self

    def _ensure_chat(self):
        """Lazily create the underlying genai chat session."""
        if self._chat is None:
            gen_config = {}
            if self._temperature is not None:
                gen_config["temperature"] = self._temperature

            model = genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=self._system_message if self._system_message else None,
                generation_config=gen_config if gen_config else None,
            )
            self._chat = model.start_chat(history=[])

    async def send_message(self, message: UserMessage) -> str:
        """
        Send a message and return the response text as a plain string.

        This is async — uses run_in_executor for the synchronous genai SDK call.
        """
        self._ensure_chat()
        parts = message.to_genai_parts()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._chat.send_message(parts)
        )

        return response.text
