import json
import pytest


@pytest.mark.requires_supabase
@pytest.mark.asyncio
async def test_mock_mcp_session_dispatches_tool(mock_mcp_session, test_user):
    uid, _ = test_user
    res = await mock_mcp_session.call_tool(
        "get_spending_by_category",
        {"user_id": uid, "date_from": "2025-01-01", "date_to": "2025-12-31"},
    )
    assert res.content
    data = json.loads(res.content[0].text)
    assert isinstance(data, list)
