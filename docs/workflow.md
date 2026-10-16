# Workflow

1. User signs in; inactive accounts are rejected. The backend computes source access from ownership and explicit user/role assignments.
2. Uploads are validated and extracted. PDF text is split per page, hashed, chunked, and indexed under a versioned document record.
3. Re-uploading unchanged content is deduplicated. Changed uploads create a new version and a deduplicated change alert. User deletion is a soft delete and creates a deletion alert so prior citations remain intact.
4. A question is validated. Explicit source selections are checked against the requesting user's permitted source IDs; retrieval is constrained to permitted sources before any content could be sent to a provider (no AI provider is configured).
5. Local retrieval scores indexed chunks using matched query terms and returns the top results with matched-term explanations, source metadata, and document dates.
6. The local answer builder uses retrieved text. Each answer claim is compared with retrieved chunk terms and labeled Supported, Partly Supported, Conflicting Information, or Not Enough Evidence. No unsupported claim is marked verified.
7. Citations are saved against each claim and its actual supporting document/chunk, including the quote and page number when available. Answer-level evidence coverage is computed from those claim results.
8. Different numeric values in passages matching the question are recorded as conflicts with side-by-side source snapshots. Admins/managers can review with a required explanation; resolution is audited.
9. Users can compare a document's stored text with its preceding version, see change alerts, and inspect a searchable table of recorded evidence activity, including candidate document relationships based on exact shared terms.
10. Authorized admins/managers can export answer/citation/conflict history in JSON or CSV. Report exports and important evidence actions are recorded in audit history.

## Current connector and temporal boundaries

- Upload processing, versioning, deletion alerts, and retrieval are active.
- Database, website/API, and cloud source records can be configured as setup-required, but no adapters, credentials vault, OAuth flow, polling schedule, or sync jobs are implemented. Manual refresh reports this limitation instead of claiming success.
- Temporal ranking uses the indexed document update timestamp only. It does not infer effective dates or determine policy authority; "latest" results explicitly do not establish authority.
- Evidence Activity shows exact shared-term evidence as candidate links in a table; these are not validated policy, department, or record relationships.
- Keyword overlap, numeric conflict detection, and evidence coverage are heuristics; they do not guarantee semantic entailment or answer correctness.
