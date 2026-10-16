# ER Diagram

```mermaid
erDiagram
    roles ||--o{ users : assigns
    roles ||--o{ role_permissions : grants
    permissions ||--o{ role_permissions : includes
    users ||--o{ data_sources : owns
    data_sources ||--o{ documents : contains
    documents ||--o{ document_chunks : splits
    users ||--o{ conversations : creates
    conversations ||--o{ queries : contains
    queries ||--o| answers : produces
    answers ||--o{ answer_claims : includes
    answer_claims ||--o{ citations : cites
    documents ||--o{ citations : referred_by
    document_chunks ||--o{ citations : supports
    queries ||--o{ retrieval_runs : runs
    retrieval_runs ||--o{ retrieval_results : returns
    document_chunks ||--o{ retrieval_results : scored
    queries ||--o{ conflicts : raises
    data_sources ||--o{ sync_jobs : syncs
    data_sources ||--o{ change_alerts : reports
    documents ||--o{ change_alerts : changed
    users ||--o{ source_access : assigned
    data_sources ||--o{ source_access : grants
    roles ||--o{ source_access : grants
    users ||--o{ feedback : leaves
    users ||--o{ audit_logs : creates
```

`answers.evidence_coverage` stores the claim-status counts and ratio for that answer.
`conflicts.evidence` stores the source snapshots shown at review time. Citations retain
quoted text, document/version linkage, page number when available, and support status;
deleting a document from search is a soft delete so older answer evidence remains
traceable. `change_alerts.dedupe_key` prevents repeated alerts for the same uploaded
version change or deletion.
