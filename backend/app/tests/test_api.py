from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import sources as sources_routes
from app.api.routes.documents import _relationship_document_label
from app.core.config import PROJECT_ROOT, Settings, normalize_database_url, settings
from app.main import app
from app.services import rag_service
from app.services import embedding_service
from app.services.rag_service import mask_sensitive_text

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_test_embedding_vectors(monkeypatch) -> None:
    class TestEmbeddings:
        def embed_query(self, text: str, **kwargs) -> list[float]:
            return [1.0, 0.0]

        def embed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(rag_service, "create_gemini_embeddings", lambda: TestEmbeddings())


def admin_headers() -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@company.com", "password": "admin123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload_text_document(headers: dict[str, str], filename: str, content: str) -> dict:
    response = client.post(
        "/api/sources/files",
        headers=headers,
        files={"file": (filename, content.encode(), "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "connected"


def test_relationship_labels_hide_generated_suffix_without_changing_dates() -> None:
    assert _relationship_document_label("travel-policy-16308a805.txt") == "travel-policy.txt"
    assert _relationship_document_label("travel-policy-12345678.txt") == "travel-policy-12345678.txt"
    assert _relationship_document_label("travel-policy-20261015.txt") == "travel-policy-20261015.txt"


def test_database_url_normalization_for_supabase() -> None:
    normalized = normalize_database_url(
        "postgresql://user:password@db.example.test:5432/postgres",
        require_ssl=True,
    )
    assert normalized.startswith("postgresql+psycopg://")
    assert "sslmode=require" in normalized


def test_database_url_normalization_preserves_sqlite() -> None:
    assert normalize_database_url("sqlite:///./test.db") == "sqlite:///./test.db"


def test_hybrid_retrieval_ranks_structured_question_over_repeated_keyword_noise() -> None:
    structured = SimpleNamespace(
        content="Unit II Q1: What is a scanner? A scanner is an input device that converts paper into digital images.",
        section_title="Unit II",
        document=SimpleNamespace(title="Computer Fundamentals"),
    )
    code_noise = SimpleNamespace(
        content="scanner scanner scanner scanner scanner scanner scanner scanner scanner",
        section_title=None,
        document=SimpleNamespace(title="Code fragments"),
    )

    hits = rag_service._hybrid_scores("What is a scanner?", [code_noise, structured])

    assert hits[0]["chunk"] is structured
    assert hits[0]["bm25_score"] > 0
    assert hits[0]["sparse_vector_score"] > 0
    assert hits[0]["matched_keywords"] == ["scanner"]


def test_claim_from_unrelated_passage_is_unsupported_and_has_no_citation() -> None:
    unrelated_hit = {
        "chunk": SimpleNamespace(content="Finance approves quarterly budget transfers."),
    }

    verified = rag_service.verify_claims(
        ["Finance approves quarterly budget transfers."],
        [unrelated_hit],
        "What is a scanner?",
    )

    assert verified[0]["support_status"] == "Unsupported"
    assert verified[0]["hit"] is None
    assert verified[0]["question_match_ratio"] == 0


def test_gemini_embedding_factory_uses_google_key_and_configured_model(monkeypatch) -> None:
    captured = {}

    class FakeGoogleEmbeddings:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(embedding_service.settings, "embedding_provider", "gemini")
    monkeypatch.setattr(embedding_service.settings, "embedding_model", "models/gemini-embedding-001")
    monkeypatch.setattr(embedding_service.settings, "google_api_key", "test-google-key")
    monkeypatch.setattr(
        "langchain_google_genai.GoogleGenerativeAIEmbeddings",
        FakeGoogleEmbeddings,
    )

    embedding_service.create_gemini_embeddings()

    assert captured == {
        "model": "models/gemini-embedding-001",
        "google_api_key": "test-google-key",
    }


def test_embedding_factory_fails_without_google_key(monkeypatch) -> None:
    monkeypatch.setattr(embedding_service.settings, "embedding_provider", "gemini")
    monkeypatch.setattr(embedding_service.settings, "google_api_key", None)
    monkeypatch.setattr(embedding_service.settings, "gemini_api_key", None)

    try:
        embedding_service.create_gemini_embeddings()
    except RuntimeError as error:
        assert "GOOGLE_API_KEY" in str(error)
    else:
        raise AssertionError("Missing embedding credentials must fail explicitly")


def test_embedding_factory_rejects_mock_provider(monkeypatch) -> None:
    monkeypatch.setattr(embedding_service.settings, "embedding_provider", "mock")

    try:
        embedding_service.create_gemini_embeddings()
    except RuntimeError as error:
        assert "mock embeddings are disabled" in str(error)
    else:
        raise AssertionError("Mock embeddings must not be selected")


def test_gemini_dense_similarity_reranks_semantic_match(monkeypatch) -> None:
    tasks = []

    class FakeEmbeddings:
        def embed_query(self, text: str, **kwargs) -> list[float]:
            tasks.append(kwargs["task_type"])
            return [1.0, 0.0]

        def embed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
            tasks.append(kwargs["task_type"])
            return [[0.0, 1.0], [1.0, 0.0]]

    monkeypatch.setattr(rag_service, "create_gemini_embeddings", lambda: FakeEmbeddings())
    hits = [
        {
            "chunk": SimpleNamespace(content="unrelated lexical hit", section_title=None),
            "document": SimpleNamespace(title="Unrelated"),
            "bm25_normalized": 0.4,
            "sparse_vector_score": 0.4,
            "score": 0.8,
        },
        {
            "chunk": SimpleNamespace(content="semantic answer", section_title="Unit II Q1"),
            "document": SimpleNamespace(title="Course Notes"),
            "bm25_normalized": 0.0,
            "sparse_vector_score": 0.0,
            "score": 0.0,
        },
    ]

    rag_service._apply_gemini_vector_scores("What does the scanner do?", hits)

    assert hits[0]["chunk"].content == "semantic answer"
    assert hits[0]["vector_score"] == 1.0
    assert tasks == ["RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"]


def test_unrelated_evidence_is_rejected_before_llm_answer_generation(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "grok")
    monkeypatch.setattr(rag_service.settings, "grok_api_key", "test-key")

    def fail_if_called(*args, **kwargs) -> None:
        raise AssertionError("LLM must not receive unrelated evidence")

    monkeypatch.setattr(rag_service.httpx, "post", fail_if_called)
    hits = [{"chunk": SimpleNamespace(content="Finance approves quarterly budget transfers.")}]

    answer, claims = rag_service.generate_answer("What is a scanner?", hits)
    verification = rag_service.verify_claims(claims, hits, "What is a scanner?")

    assert "do not directly answer" in answer
    assert verification[0]["support_status"] == "Unsupported"
    assert verification[0]["hit"] is None


def test_dotenv_is_loaded_from_project_root_independent_of_working_directory() -> None:
    dotenv = Settings.model_config["env_file"]
    assert Path(dotenv) == PROJECT_ROOT / ".env"
    assert Path(dotenv).is_absolute()


def test_supabase_database_url_overrides_local_fallback() -> None:
    config = Settings(
        database_url="sqlite:///./local.db",
        supabase_db_url="postgres://user:password@db.example.test:5432/postgres",
    )
    active_url = config.active_database_url
    assert active_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in active_url


def test_cors_origins_accept_comma_separated_and_json_values() -> None:
    comma_separated = Settings(backend_cors_origins="http://localhost:5173, http://127.0.0.1:5173")
    json_array = Settings(backend_cors_origins='["http://localhost:5173","http://127.0.0.1:5173"]')
    expected = ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert comma_separated.cors_origins == expected
    assert json_array.cors_origins == expected


def test_supabase_project_api_url_is_rejected() -> None:
    config = Settings(supabase_db_url="https://example.supabase.co")
    try:
        config.active_database_url
    except ValueError as error:
        assert "PostgreSQL connection string" in str(error)
    else:
        raise AssertionError("HTTPS Supabase API URL should not be accepted as a database URL")


def test_grok_answer_returns_complete_text_and_splits_claims(monkeypatch) -> None:
    answer_text = " ".join(f"Complete evidence-backed sentence {index}." for index in range(30))
    monkeypatch.setattr(rag_service.settings, "llm_provider", "grok")
    monkeypatch.setattr(rag_service.settings, "grok_api_key", "test-key")

    class FakeResponse:
        is_success = True

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": answer_text}, "finish_reason": "stop"}]}

    monkeypatch.setattr(rag_service.httpx, "post", lambda *args, **kwargs: FakeResponse())
    chunk = SimpleNamespace(content="Complete evidence-backed sentence 1.", page_number=1)
    document = SimpleNamespace(title="Evidence", version="1", updated_at=None)
    source = SimpleNamespace(name="Upload")
    hits = [{"chunk": chunk, "document": document, "source": source}]

    full_answer, claims = rag_service.generate_answer("Complete evidence-backed sentence", hits)

    assert full_answer == answer_text
    assert len(full_answer) > 260
    assert len(claims) == 30


def test_grok_answer_continues_when_provider_reports_output_limit(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "xai")
    monkeypatch.setattr(rag_service.settings, "grok_api_key", "test-key")
    responses = [
        {"choices": [{"message": {"content": "First part."}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "Second part."}, "finish_reason": "stop"}]},
    ]

    class FakeResponse:
        is_success = True

        def __init__(self, payload: dict):
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    monkeypatch.setattr(
        rag_service.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(responses.pop(0)),
    )
    chunk = SimpleNamespace(content="Source evidence.", page_number=None)
    document = SimpleNamespace(title="Evidence", version="1", updated_at=None)
    source = SimpleNamespace(name="Upload")

    full_answer, _ = rag_service.generate_answer(
        "Explain source evidence",
        [{"chunk": chunk, "document": document, "source": source}],
    )

    assert full_answer == "First part.\n\nSecond part."


def test_grok_authentication_error_explains_key_rejection(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "grok")
    monkeypatch.setattr(rag_service.settings, "grok_api_key", "test-key")

    class FakeResponse:
        is_success = False
        status_code = 401

    monkeypatch.setattr(rag_service.httpx, "post", lambda *args, **kwargs: FakeResponse())
    chunk = SimpleNamespace(content="Source evidence.", page_number=None)
    document = SimpleNamespace(title="Evidence", version="1", updated_at=None)
    source = SimpleNamespace(name="Upload")
    try:
        rag_service.generate_answer(
            "Explain source evidence",
            [{"chunk": chunk, "document": document, "source": source}],
        )
    except RuntimeError as error:
        assert "xAI rejected the API key" in str(error)
    else:
        raise AssertionError("Expected invalid xAI credentials to produce an actionable error")


def test_grok_provider_error_is_returned_as_gateway_error(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "grok")
    monkeypatch.setattr(rag_service.settings, "grok_api_key", "test-key")

    class FakeResponse:
        is_success = False
        status_code = 401

    monkeypatch.setattr(rag_service.httpx, "post", lambda *args, **kwargs: FakeResponse())
    headers = admin_headers()
    upload_text_document(
        headers,
        f"grok-error-{uuid4().hex}.txt",
        "A company travel policy sets a daily meal allowance of AED 50.",
    )

    response = client.post(
        "/api/chat",
        json={"question": "What is the daily meal allowance?"},
        headers=headers,
    )

    assert response.status_code == 502
    assert "xAI rejected the API key" in response.json()["detail"]


def test_grok_rate_limit_error_is_actionable() -> None:
    response = SimpleNamespace(status_code=429)
    error = rag_service._grok_request_error(response)
    assert "quota" in str(error).lower()


def test_gemini_answer_uses_backend_key_and_parses_response(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "gemini")
    monkeypatch.setattr(rag_service.settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(rag_service.settings, "google_api_key", None)
    monkeypatch.setattr(rag_service.settings, "gemini_model", "gemini-test-model")
    requests = []

    class FakeResponse:
        is_success = True

        def json(self) -> dict:
            return {
                "candidates": [{
                    "content": {"parts": [{"text": "The policy requires MFA [1]."}]},
                    "finishReason": "STOP",
                }],
            }

    def fake_post(url: str, **kwargs) -> FakeResponse:
        requests.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(rag_service.httpx, "post", fake_post)
    chunk = SimpleNamespace(content="The policy requires MFA.", page_number=2)
    document = SimpleNamespace(title="Security Policy", version="1", updated_at=None)
    source = SimpleNamespace(name="Company uploads")

    answer, claims = rag_service.generate_answer(
        "What does the policy require?",
        [{"chunk": chunk, "document": document, "source": source}],
    )

    assert answer == "The policy requires MFA [1]."
    assert claims == ["The policy requires MFA [1]."]
    assert len(requests) == 1
    url, request = requests[0]
    assert url.endswith("/models/gemini-test-model:generateContent")
    assert request["headers"]["x-goog-api-key"] == "test-gemini-key"
    assert "test-gemini-key" not in url
    assert "Security Policy" in request["json"]["contents"][0]["parts"][0]["text"]
    assert "shared keywords alone do not establish relevance" in request["json"]["systemInstruction"]["parts"][0]["text"]


def test_gemini_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(rag_service.settings, "llm_provider", "gemini")
    monkeypatch.setattr(rag_service.settings, "gemini_api_key", None)
    chunk = SimpleNamespace(content="Source evidence.", page_number=None)
    document = SimpleNamespace(title="Evidence", version="1", updated_at=None)
    source = SimpleNamespace(name="Upload")

    try:
        rag_service.generate_answer(
            "Explain source evidence",
            [{"chunk": chunk, "document": document, "source": source}],
        )
    except ValueError as error:
        assert "GEMINI_API_KEY" in str(error)
    else:
        raise AssertionError("Expected missing Gemini credentials to produce an actionable error")


def test_sensitive_identifiers_are_masked() -> None:
    masked = mask_sensitive_text(
        "Contact alice@example.com; password=supersecret; call (555) 123-4567."
    )
    assert "alice@example.com" not in masked
    assert "supersecret" not in masked
    assert "123-4567" not in masked


def test_source_url_rejects_embedded_credentials() -> None:
    response = client.post(
        "/api/sources/website",
        headers=admin_headers(),
        json={"name": "Unsafe URL", "url": "https://example.com/crawl?api_key=secret"},
    )
    assert response.status_code == 400


def test_login_and_me() -> None:
    headers = admin_headers()
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin@company.com"


def test_chat_flow() -> None:
    headers = admin_headers()
    first = upload_text_document(
        headers,
        f"policy-{uuid4().hex}.txt",
        "The windshield deductible is AED 500.",
    )
    second = upload_text_document(
        headers,
        f"claims-{uuid4().hex}.txt",
        "The windshield deductible is AED 1,000.",
    )
    response = client.post(
        "/api/chat",
        json={"question": "What is the windshield deductible?"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "answer" in payload
    assert payload["citations"]
    assert payload["answer"]["verification_status"] in {
        "Supported",
        "Partly Supported",
        "Conflicting Information",
        "Not Enough Evidence",
        "Unsupported",
    }
    assert payload["evidence_coverage"]["total"] == len(payload["claims"])
    assert all(citation["document_id"] and citation["quote"] for citation in payload["citations"])
    assert "not a guarantee" in payload["coverage_disclaimer"]
    assert payload["conflicts"]
    assert all(len(conflict["evidence"]) >= 2 for conflict in payload["conflicts"])
    assert all(
        len({tuple(item["values"]) for item in conflict["evidence"]}) >= 2
        for conflict in payload["conflicts"]
    )
    assert payload["answer"]["verification_status"] == "Conflicting Information"
    graph = client.get("/api/documents/relationships/map", headers=headers)
    assert graph.status_code == 200
    graph_nodes = graph.json()["nodes"]
    assert any(node["type"] == "conflict" for node in graph_nodes)
    assert any(
        edge["type"] == "records disagreement"
        for edge in graph.json()["edges"]
    )
    saved_conflicts = client.get("/api/conflicts", headers=headers)
    saved_conflict = next(item for item in saved_conflicts.json() if item["subject"] == "What is the windshield deductible?")
    reviewed = client.post(
        f"/api/conflicts/{saved_conflict['id']}/review",
        headers=headers,
        json={"resolution": "The policy owner confirmed that the documents apply to different filing conditions."},
    )
    assert reviewed.status_code == 200
    audit = client.get("/api/audit-logs", headers=headers)
    assert any(item["action"] == "conflict_resolved" for item in audit.json())
    assert client.delete(f"/api/sources/{first['source_id']}", headers=headers).status_code == 200
    assert client.delete(f"/api/sources/{second['source_id']}", headers=headers).status_code == 200


def test_unsupported_answer_is_not_verified() -> None:
    response = client.post(
        "/api/chat",
        json={"question": "Which orbital telescope color is assigned to finance?"},
        headers=admin_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]["verification_status"] == "Unsupported"
    assert payload["citations"] == []
    assert payload["evidence_coverage"]["Unsupported"] == 1


def test_source_permission_is_enforced_for_explicit_source_selection() -> None:
    headers = admin_headers()
    source = upload_text_document(headers, f"restricted-{uuid4().hex}.txt", "Restricted company policy data.")
    email = f"employee-{uuid4().hex}@example.com"
    registered = client.post("/api/auth/register", json={
        "name": "Test Employee",
        "email": email,
        "password": "secure-test-password",
    })
    assert registered.status_code == 200, registered.text
    employee_headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    denied = client.post(
        "/api/chat",
        json={"question": "What is company policy data?", "source_ids": [source["source_id"]]},
        headers=employee_headers,
    )
    assert denied.status_code == 403
    granted = client.post(
        f"/api/sources/{source['source_id']}/access",
        headers=headers,
        json={"user_id": registered.json()["user"]["id"], "permission_level": "read"},
    )
    assert granted.status_code == 200, granted.text
    shared_document = next(
        document for document in client.get("/api/documents", headers=employee_headers).json()
        if document["source_id"] == source["source_id"]
    )
    assert shared_document["can_delete"] is False
    denied_delete = client.delete(
        f"/api/documents/{shared_document['id']}",
        headers=employee_headers,
    )
    assert denied_delete.status_code == 404
    allowed = client.post(
        "/api/chat",
        json={"question": "What is company policy data?", "source_ids": [source["source_id"]]},
        headers=employee_headers,
    )
    assert allowed.status_code == 200
    answer_id = allowed.json()["answer_id"]
    revoked = client.delete(
        f"/api/sources/{source['source_id']}/access/{granted.json()['id']}",
        headers=headers,
    )
    assert revoked.status_code == 200
    saved_evidence = client.get(
        f"/api/answers/{answer_id}/evidence",
        headers=employee_headers,
    )
    assert saved_evidence.status_code == 200
    explorer = client.get("/api/reports/evidence/explorer", headers=employee_headers)
    assert explorer.status_code == 200
    saved_report = next(
        report for report in explorer.json()["reports"]
        if report["answer_id"] == answer_id
    )
    if saved_evidence.json()["claims"]:
        assert all(
            claim["claim_text"] == "Claim hidden because source access has changed."
            for claim in saved_evidence.json()["claims"]
        )
        assert all(claim["status"] == "Not verified" for claim in saved_report["claims"])
        assert all(not claim["evidence"] for claim in saved_report["claims"])
    denied_after_revoke = client.post(
        "/api/chat",
        json={"question": "What is company policy data?", "source_ids": [source["source_id"]]},
        headers=employee_headers,
    )
    assert denied_after_revoke.status_code == 403
    assert client.delete(f"/api/sources/{source['source_id']}", headers=headers).status_code == 200


def test_reports_endpoint() -> None:
    response = client.get("/api/reports/summary", headers=admin_headers())
    assert response.status_code == 200
    assert "connected_sources" in response.json()


def test_runtime_settings_are_authenticated_and_never_return_provider_secrets(monkeypatch) -> None:
    headers = admin_headers()
    monkeypatch.setattr(settings, "llm_provider", "grok")
    monkeypatch.setattr(settings, "grok_api_key", "secret-test-key")
    monkeypatch.setattr(settings, "grok_model", "grok-test-model")
    monkeypatch.setattr(settings, "grok_api_url", "https://api.x.ai/v1/chat/completions")
    monkeypatch.setattr(settings, "google_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "secret-gemini-embedding-key")

    response = client.get("/api/settings/runtime", headers=headers)
    assert response.status_code == 200
    assert response.json()["llm"] == {
        "provider": "Grok (xAI)",
        "status": "untested",
        "credentials_configured": True,
        "model": "grok-test-model",
        "endpoint_host": "api.x.ai",
        "diagnostic": "Credentials and model have not been verified against xAI.",
    }
    assert "secret-test-key" not in response.text
    assert response.json()["embeddings"]["provider"] == "gemini"
    assert response.json()["embeddings"]["model"] == "models/gemini-embedding-001"
    assert response.json()["embeddings"]["status"] == "configured"
    assert "secret-gemini-embedding-key" not in response.text
    assert response.json()["source_connectors"]["cloud_storage"] == "unavailable"
    assert client.get("/api/settings/runtime").status_code == 401


def test_gemini_runtime_settings_report_key_presence_without_exposing_secret(monkeypatch) -> None:
    headers = admin_headers()
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "secret-gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test-model")
    monkeypatch.setattr(settings, "gemini_api_url", "https://generativelanguage.googleapis.com/v1beta")

    response = client.get("/api/settings/runtime", headers=headers)

    assert response.status_code == 200
    assert response.json()["llm"] == {
        "provider": "Gemini (Google)",
        "status": "untested",
        "credentials_configured": True,
        "model": "gemini-test-model",
        "endpoint_host": "generativelanguage.googleapis.com",
        "diagnostic": "Credentials and model have not been verified against Google.",
    }
    assert "secret-gemini-key" not in response.text


def test_conversation_history_links_latest_answer_and_delete_is_owner_scoped() -> None:
    headers = admin_headers()
    question = f"History item {uuid4().hex}"
    answer = client.post("/api/chat", json={"question": question}, headers=headers)
    assert answer.status_code == 200, answer.text
    conversation_id = answer.json()["conversation_id"]
    reports = client.get("/api/reports/evidence/explorer", headers=headers)
    saved_report = next(
        report for report in reports.json()["reports"]
        if report["answer_id"] == answer.json()["answer_id"]
    )
    saved_query_id = saved_report["query_id"]

    history = client.get("/api/conversations", headers=headers)
    item = next(row for row in history.json() if row["id"] == conversation_id)
    assert item["latest_query_id"] == saved_query_id
    assert saved_query_id in item["query_ids"]
    assert item["title"] == question[:80]

    registered = client.post("/api/auth/register", json={
        "name": "History Reader",
        "email": f"history-{uuid4().hex}@example.com",
        "password": "secure-test-password",
    })
    reader_headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    assert client.delete(f"/api/conversations/{conversation_id}", headers=reader_headers).status_code == 404
    assert client.delete(f"/api/conversations/{conversation_id}", headers=headers).status_code == 200
    assert client.get("/api/conversations", headers=headers).status_code == 200
    assert all(row["id"] != conversation_id for row in client.get("/api/conversations", headers=headers).json())


def test_evidence_report_exports_json_and_csv() -> None:
    headers = admin_headers()
    json_response = client.get("/api/reports/export?format=json", headers=headers)
    csv_response = client.get("/api/reports/export?format=csv", headers=headers)
    assert json_response.status_code == 200
    assert "answers" in json_response.json()
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "verification_status" in csv_response.text


def test_evidence_explorer_returns_permission_scoped_claim_evidence() -> None:
    headers = admin_headers()
    uploaded = upload_text_document(
        headers,
        f"evidence-explorer-{uuid4().hex}.txt",
        "Employee leave policy provides 20 days of annual leave.",
    )
    question = f"How many annual leave days are provided? {uuid4().hex}"
    answer = client.post("/api/chat", json={"question": question}, headers=headers)
    assert answer.status_code == 200, answer.text

    explorer = client.get("/api/reports/evidence/explorer", headers=headers)
    assert explorer.status_code == 200
    report = next(item for item in explorer.json()["reports"] if item["question"] == question)
    assert report["answer_id"] == answer.json()["answer_id"]
    assert report["question"] == question
    assert report["answer"]
    assert report["created_at"]
    assert report["sources_examined"] >= 1
    assert report["claims"]
    evidence = [item for claim in report["claims"] for item in claim["evidence"]]
    assert any(item["source_id"] == uploaded["source_id"] for item in evidence)
    assert all(item["quote"] and item["document_name"] for item in evidence)

    registered = client.post("/api/auth/register", json={
        "name": "Report Reader",
        "email": f"reader-{uuid4().hex}@example.com",
        "password": "secure-test-password",
    })
    reader_headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    reader_reports = client.get("/api/reports/evidence/explorer", headers=reader_headers)
    assert reader_reports.status_code == 200
    assert all(item["question"] != question for item in reader_reports.json()["reports"])


def test_relationship_map_contains_source_documents() -> None:
    headers = admin_headers()
    suffix = uuid4().hex
    first_filename = f"travel-policy-{suffix}.txt"
    second_filename = f"travel-rules-{suffix}.txt"
    first = upload_text_document(
        headers,
        first_filename,
        "Corporate travel expense policy applies to employee operations and managers.",
    )
    second = upload_text_document(
        headers,
        second_filename,
        "Corporate travel expense policy covers remote employees and managers.",
    )
    question = f"What is the corporate travel expense policy? {suffix}"
    answer = client.post("/api/chat", json={"question": question}, headers=headers)
    assert answer.status_code == 200, answer.text

    response = client.get("/api/documents/relationships/map", headers=headers)
    assert response.status_code == 200
    graph = response.json()
    assert graph["nodes"]
    assert graph["basis"]
    assert any(node["type"] == "question" and node["label"] == question for node in graph["nodes"])
    assert any(node["type"] == "claim" for node in graph["nodes"])
    assert any(node["type"] == "evidence" for node in graph["nodes"])
    document_nodes = [node for node in graph["nodes"] if node["type"] == "document"]
    assert any(node["label"] == "travel-policy.txt" and node["details"]["filename"] == first_filename for node in document_nodes)
    assert any(node["label"] == "travel-rules.txt" and node["details"]["filename"] == second_filename for node in document_nodes)
    assert any(edge["type"] == "cited evidence" for edge in graph["edges"])
    keyword_edges = [edge for edge in graph["edges"] if edge["type"] == "possible topical overlap"]
    assert keyword_edges
    assert all(edge["candidate"] for edge in keyword_edges)
    assert all("candidate" in edge["explanation"].lower() for edge in keyword_edges)

    registered = client.post("/api/auth/register", json={
        "name": "Relationship Reader",
        "email": f"graph-reader-{suffix}@example.com",
        "password": "secure-test-password",
    })
    reader_headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    reader_graph = client.get("/api/documents/relationships/map", headers=reader_headers)
    assert reader_graph.status_code == 200
    assert all(
        node["details"].get("source_id") != first["source_id"]
        for node in reader_graph.json()["nodes"]
    )

    assert client.delete(f"/api/sources/{first['source_id']}", headers=headers).status_code == 200
    assert client.delete(f"/api/sources/{second['source_id']}", headers=headers).status_code == 200


def test_upload_versions_are_compared_and_alerted(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sources_routes, "ensure_upload_directory", lambda _: tmp_path)
    headers = admin_headers()
    filename = f"versioned-policy-{uuid4().hex}.txt"
    first = client.post(
        "/api/sources/files",
        headers=headers,
        files={"file": (filename, b"Policy deductible is AED 500.", "text/plain")},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/sources/files",
        headers=headers,
        files={"file": (filename, b"Policy deductible is AED 750 after renewal.", "text/plain")},
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == "v2"
    graph = client.get("/api/documents/relationships/map", headers=headers)
    assert graph.status_code == 200
    assert any(node["type"] == "document version" and node["details"]["version"] == "v2" for node in graph.json()["nodes"])
    assert any(edge["type"] == "version of" for edge in graph.json()["edges"])
    time_aware = client.post(
        "/api/chat",
        json={"question": "What changed this month?"},
        headers=headers,
    )
    assert time_aware.status_code == 200
    assert any(event["document"] == filename for event in time_aware.json()["change_events"])
    assert time_aware.json()["answer"]["verification_status"] == "Not Enough Evidence"
    comparison = client.get(
        f"/api/documents/{second.json()['document_id']}/compare",
        headers=headers,
    )
    assert comparison.status_code == 200
    assert comparison.json()["previous_version"] == "v1"
    assert comparison.json()["changes"]
    alerts = client.get("/api/change-alerts", headers=headers)
    assert alerts.status_code == 200
    assert any(
        alert["event_type"] == "modified" and alert["document"] == filename
        for alert in alerts.json()
    )
    removed_document = client.delete(
        f"/api/documents/{second.json()['document_id']}",
        headers=headers,
    )
    assert removed_document.status_code == 200
    visible_documents = client.get("/api/documents", headers=headers).json()
    assert all(document["id"] != second.json()["document_id"] for document in visible_documents)
    refreshed_alerts = client.get("/api/change-alerts", headers=headers)
    assert any(
        alert["event_type"] == "deleted" and alert["document"] == filename
        for alert in refreshed_alerts.json()
    )
    deleted = client.delete(f"/api/sources/{first.json()['source_id']}", headers=headers)
    assert deleted.status_code == 200
