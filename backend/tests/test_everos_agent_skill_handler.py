from app.everos.memory.cascade.handlers import agent_skill


class _FailingEmbedder:
    async def embed(self, _text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


async def test_agent_skill_embedding_falls_back_to_zero_vector_when_unavailable():
    vector = await agent_skill._embed_skill_anchor(
        _FailingEmbedder(),
        "Security audit\nFind command injection issues.",
    )

    assert vector == [0.0] * agent_skill.AGENT_SKILL_VECTOR_DIM
