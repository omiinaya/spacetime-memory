"""Debug test for test_search_keyword - v2"""
from unittest.mock import Mock
from tests.conftest import make_sql_response


def test_debug_side_effect(mock_http_client):
    """Verify side_effect properly intercepts tantivy calls."""
    
    def _side_effect(*args, **kwargs):
        url = str(args[0]) if args else ""
        print(f"  side_effect: url={url!r}")
        
        # Match tantivy by checking URL path
        if "/search" in url:
            print(f"  -> tantivy search response (json=lambda: [])")
            resp = Mock(status_code=200, text="[]")
            resp.json = lambda: []
            return resp
        if "/embeddings" in url:
            resp = Mock(status_code=200)
            resp.json = lambda: {"data": [{"embedding": [0.0]}]}
            return resp
        # Default SQL
        resp = Mock(status_code=200)
        resp.text = make_sql_response([])
        return resp

    mock_http_client._http.post.side_effect = _side_effect
    
    result = mock_http_client.search(
        workspace_id="ws1",
        query="pizza",
        semantic=False,
    )
    
    print(f"Result: {result}")
    print(f"Result type: {type(result).__name__}")
    print(f"Result length: {len(result)}")
