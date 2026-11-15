"""Scripted Gemini mock for integration tests.

Usage:
    client = MockGeminiClient()
    client.enqueue([ChunkText("Hi ")])  # round 1
    client.enqueue([ChunkToolCall("get_x", {"a": 1})])  # round 2

Each call to generate_content_stream pops one round from the queue and
yields its chunks. If the queue is empty, raises RuntimeError — indicates
the test under-scripted the conversation.
"""
from dataclasses import dataclass, field
from typing import AsyncIterator, Any
from unittest.mock import MagicMock


@dataclass
class ChunkText:
    text: str
    function_calls: list = field(default_factory=list)


@dataclass
class _FC:
    name: str
    args: dict


@dataclass
class ChunkToolCall:
    name: str
    args: dict
    text: str = ""

    @property
    def function_calls(self):
        return [_FC(self.name, self.args)]


class _AioModels:
    def __init__(self, owner: "MockGeminiClient"):
        self._owner = owner

    async def generate_content_stream(self, *, model, contents, config):
        if not self._owner._rounds:
            raise RuntimeError("MockGeminiClient: no more scripted rounds; test under-scripted")
        round_chunks = self._owner._rounds.pop(0)
        self._owner.calls.append({"model": model, "contents": contents, "config": config})

        async def _gen():
            for c in round_chunks:
                yield c

        return _gen()


class _Aio:
    def __init__(self, owner):
        self.models = _AioModels(owner)


class MockGeminiClient:
    def __init__(self):
        self._rounds: list[list] = []
        self.calls: list[dict] = []
        self.aio = _Aio(self)

    def enqueue(self, chunks: list):
        self._rounds.append(chunks)
