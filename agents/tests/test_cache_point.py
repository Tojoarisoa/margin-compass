from mc_agents.llm import LLMRequest

TOOL = {"toolSpec": {"name": "t", "inputSchema": {"json": {"type": "object"}}}}


def _req(**kw):
    return LLMRequest("m", "sys", [{"role": "user", "content": [{"text": "q"}]}], [TOOL], **kw)


def test_default_has_no_cache_point_and_hash_is_stable(monkeypatch):
    monkeypatch.delenv("MC_CACHE_PROMPT", raising=False)
    c = _req().to_converse()
    assert c["system"] == [{"text": "sys"}]
    assert c["toolConfig"]["tools"] == [TOOL]
    assert _req().sha() == _req(cache_prompt=False).sha()


def test_cache_prompt_adds_cache_points_after_system_and_tools(monkeypatch):
    monkeypatch.delenv("MC_CACHE_PROMPT", raising=False)
    c = _req(cache_prompt=True).to_converse()
    assert c["system"][-1] == {"cachePoint": {"type": "default"}}
    assert c["toolConfig"]["tools"] == [TOOL, {"cachePoint": {"type": "default"}}]
    assert _req(cache_prompt=True).sha() != _req().sha()


def test_no_tools_no_tool_config():
    r = LLMRequest("m", "s", [], [], cache_prompt=True).to_converse()
    assert "toolConfig" not in r


def test_env_flag_turns_cache_prompt_on(monkeypatch):
    monkeypatch.delenv("MC_CACHE_PROMPT", raising=False)
    assert LLMRequest("m", "s", [], []).cache_prompt is False
    monkeypatch.setenv("MC_CACHE_PROMPT", "1")
    assert LLMRequest("m", "s", [], []).cache_prompt is True
