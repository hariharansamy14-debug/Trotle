import { useEffect, useState, type SVGProps } from 'react'
import {
  Bell,
  FileText,
  Folder,
  GitCompare,
  History,
  List,
  LogOut,
  MessageSquareText,
  Search,
  Settings,
  ShieldCheck,
  Scale,
  UserCog,
} from 'lucide-react'
import './App.css'

type User = {
  id: number
  name: string
  email: string
  role: string
}

type ManagedUser = {
  id: number
  name: string
  email: string
  role: string
  status: string
}

type ConversationItem = {
  id: number
  title: string
  updated_at: string
  latest_query_id: number | null
  query_ids: number[]
}

type SourceItem = {
  id: number
  name: string
  source_type: string
  connection_status: string
  documents_count: number
  last_sync_at?: string | null
}

type DocumentItem = {
  id: number
  title: string
  version: string | null
  status: string
  source_id: number
  source_url: string | null
  can_delete?: boolean
}

type EvidenceClaim = {
  claim: string
  support_status: string
  match_ratio: number
}

type CitationCard = {
  id: number
  documentId: number
  title: string
  detail: string
  snippet: string
  status: string
  relevance: number
}

type ReportSummary = {
  connected_sources: number
  ready_documents: number
  failed_processing_jobs: number
  questions_asked: number
  evidence_status: { supported: number; conflicting: number }
}

type EvidenceReportItem = {
  query_id: number
  question: string
  answer_id: number
  answer: string
  verification_status: string
  coverage: Record<string, number>
  created_at: string
  sources_examined: number
  claims: Array<{
    id: number
    text: string
    status: string
    limitation: string | null
    evidence: Array<{
      id: number
      document_id: number | null
      source_id: number
      document_name: string
      source_name: string
      source_type: string | null
      quote: string
      page: number | null
      section: string | null
      version: string | null
      created_at: string | null
      updated_at: string | null
      source_url: string | null
      status: string
    }>
  }>
  conflicts: Array<{
    id: number
    subject: string
    status: string
    summary: string
    resolution: string | null
    created_at: string
    evidence: Array<Record<string, unknown> & {
      document_name: string
      quote: string
      source_id?: number
      page?: number | null
      version?: string | null
      values?: string[]
    }>
  }>
}

type RuntimeSettings = {
  llm: { provider: string; status: string; credentials_configured: boolean; model: string | null; endpoint_host: string | null; diagnostic: string }
  embeddings: { provider: string; status: string; model?: string; diagnostic: string }
  retrieval: { method: string; maximum_results: number }
  source_connectors: Record<string, string>
}

type RelationshipRecord = {
  id: string
  type: 'question' | 'claim' | 'document' | 'document version' | 'evidence' | 'conflict'
  label: string
  details: Record<string, string | number | boolean | string[] | null | undefined>
}

type EvidenceLink = {
  id: string
  from: string
  to: string
  type: string
  candidate: boolean
  explanation: string
  details: Record<string, string | number | string[] | null | undefined>
}

type EvidenceActivity = {
  nodes: RelationshipRecord[]
  edges: EvidenceLink[]
  basis: string
  truncated: boolean
}

const navItems = [
  { key: 'chat', label: 'Answer Check', icon: MessageSquareText },
  { key: 'history', label: 'Search History', icon: History },
  { key: 'sources', label: 'Data Sources', icon: Folder },
  { key: 'documents', label: 'Documents', icon: FileText },
  { key: 'conflicts', label: 'Conflicts', icon: Scale },
  { key: 'alerts', label: 'Change Alerts', icon: Bell },
  { key: 'versions', label: 'Compare Versions', icon: GitCompare },
  { key: 'coverage', label: 'Evidence Coverage', icon: ShieldCheck },
  { key: 'relationships', label: 'Evidence Activity', icon: List },
  { key: 'reports', label: 'Evidence Reports', icon: BarChartIcon },
  { key: 'users', label: 'User Management', icon: UserCog },
  { key: 'settings', label: 'Settings', icon: Settings },
]

function BarChartIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}>
      <path d="M4 18V8M10 18V4M16 18v-7M22 18V10" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function authorizedFetch(path: string, token: string, init: RequestInit = {}) {
  return fetch(`http://localhost:8000${path}`, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
    },
  })
}

function App() {
  const [currentPage, setCurrentPage] = useState('chat')
  const [question, setQuestion] = useState('What is our motor vehicle windshield damage deductible?')
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('rag-token'))
  const [user, setUser] = useState<User | null>(null)
  const [managedUsers, setManagedUsers] = useState<ManagedUser[]>([])
  const [conversations, setConversations] = useState<ConversationItem[]>([])
  const [historySearch, setHistorySearch] = useState('')
  const [sources, setSources] = useState<SourceItem[]>([])
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [conflicts, setConflicts] = useState<Array<{ id: number; subject: string; summary: string; status: string; evidence: Array<{ document_name: string; page: number | null; quote: string; values?: string[] }> }>>([])
  const [changeAlerts, setChangeAlerts] = useState<Array<{ id: number; document: string; event_type: string; summary: string; created_at: string; reviewed: boolean }>>([])
  const [changeEvents, setChangeEvents] = useState<Array<{ id: number; document: string; event_type: string; summary: string; created_at: string }>>([])
  const [selectedDocumentId, setSelectedDocumentId] = useState('')
  const [openDocumentId, setOpenDocumentId] = useState<number | null>(null)
  const [documentEvidence, setDocumentEvidence] = useState<Array<{ id: number; content: string; page_number: number | null; section_title: string | null }>>([])
  const [versionComparison, setVersionComparison] = useState<{ current_version?: string; previous_version?: string | null; changes?: Array<{ type: string; previous: string[]; current: string[] }>; message?: string } | null>(null)
  const [relationshipData, setRelationshipData] = useState<EvidenceActivity>({ nodes: [], edges: [], basis: '', truncated: false })
  const [relationshipSearch, setRelationshipSearch] = useState('')
  const [relationshipEdgeFilter, setRelationshipEdgeFilter] = useState('all')
  const [coverageSummary, setCoverageSummary] = useState<{ claims: Record<string, number>; coverage_disclaimer: string } | null>(null)
  const [evidenceReports, setEvidenceReports] = useState<EvidenceReportItem[]>([])
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null)
  const [reportSearch, setReportSearch] = useState('')
  const [claimFilter, setClaimFilter] = useState('All claims')
  const [explainedClaimId, setExplainedClaimId] = useState<number | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState('')
  const [reportMessage, setReportMessage] = useState('')
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings | null>(null)
  const [whyResults, setWhyResults] = useState<Array<{ document_name: string; source: string | null; matched_keywords: string[]; relevance_score: number; document_date: string | null; source_type: string | null }>>([])
  const [claims, setClaims] = useState<EvidenceClaim[]>([])
  const [coverage, setCoverage] = useState<Record<string, number | string> | null>(null)
  const [showWhyResults, setShowWhyResults] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pageError, setPageError] = useState('')
  const [askError, setAskError] = useState('')
  const [reports, setReports] = useState<ReportSummary>({
    connected_sources: 0,
    ready_documents: 0,
    failed_processing_jobs: 0,
    questions_asked: 0,
    evidence_status: { supported: 0, conflicting: 0 },
  })
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [answer, setAnswer] = useState({
    text: 'Ask a question to retrieve evidence from sources you are permitted to access.',
    status: 'Not Enough Evidence',
  })
  const [evidenceCards, setEvidenceCards] = useState<CitationCard[]>([])
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')
  const [deletingDocumentIds, setDeletingDocumentIds] = useState<number[]>([])

  useEffect(() => {
    if (!token) return
    const loadSession = async () => {
      const response = await fetch('http://localhost:8000/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
      }
    }
    loadSession()
  }, [token, user?.role])

  useEffect(() => {
    if (!token) return
    fetch('http://localhost:8000/api/sources', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => setSources(Array.isArray(data) ? data : []))
      .catch(() => setSources([]))

    fetch('http://localhost:8000/api/reports/summary', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setReports(data))
      .catch(() => undefined)
  }, [token])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    const loadEvidenceWorkspace = async () => {
      try {
        const responses = await Promise.all([
          authorizedFetch('/api/documents', token),
          authorizedFetch('/api/conflicts', token),
          authorizedFetch('/api/change-alerts', token),
          authorizedFetch('/api/documents/relationships/map', token),
          authorizedFetch('/api/conversations', token),
          authorizedFetch('/api/settings/runtime', token),
        ])
        const failed = responses.find((response) => !response.ok)
        if (failed) throw new Error('Could not load evidence workspace data.')
        const [documentData, conflictData, alertData, mapData, conversationData, runtimeData] = await Promise.all(responses.map((response) => response.json()))
        if (cancelled) return
        setDocuments(documentData)
        setConflicts(conflictData)
        setChangeAlerts(alertData)
        setRelationshipData(mapData)
        setConversations(conversationData)
        setRuntimeSettings(runtimeData)
        if (user?.role.toLowerCase() === 'admin') {
          const usersResponse = await authorizedFetch('/api/users', token)
          if (usersResponse.ok && !cancelled) setManagedUsers(await usersResponse.json())
        }
        const reportResponse = await authorizedFetch('/api/reports/evidence', token)
        if (reportResponse.ok && !cancelled) setCoverageSummary(await reportResponse.json())
        if (!cancelled) setReportLoading(true)
        const explorerResponse = await authorizedFetch('/api/reports/evidence/explorer', token)
        if (!explorerResponse.ok) {
          const errorData = await explorerResponse.json()
          throw new Error(errorData.detail || 'Could not load evidence reports.')
        }
        const explorerData = await explorerResponse.json()
        if (!cancelled) {
          const loadedReports = explorerData.reports as EvidenceReportItem[]
          setEvidenceReports(loadedReports)
          setSelectedReportId((current) => current && loadedReports.some((report) => report.query_id === current)
            ? current
            : loadedReports[0]?.query_id ?? null)
          setReportError('')
        }
      } catch (error) {
        if (!cancelled) {
          setPageError(error instanceof Error ? error.message : 'Could not load evidence workspace data.')
          setReportError(error instanceof Error ? error.message : 'Could not load evidence reports.')
        }
      } finally {
        if (!cancelled) setReportLoading(false)
      }
    }
    void loadEvidenceWorkspace()
    return () => { cancelled = true }
  }, [token, user?.role])

  const handleLogin = async (email: string, password: string) => {
    if (authLoading) return
    setAuthLoading(true)
    setAuthError('')
    try {
      const response = await fetch('http://localhost:8000/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (response.status === 401) {
        setAuthError('Email or password is incorrect.')
        return
      }
      if (!response.ok) {
        setAuthError(`Sign in failed (HTTP ${response.status}). Check the backend service and try again.`)
        return
      }
      const data = await response.json()
      setToken(data.access_token)
      localStorage.setItem('rag-token', data.access_token)
      setUser(data.user)
    } catch {
      setAuthError('Cannot reach the backend at localhost:8000. Start the API and verify its database connection, then try again.')
    } finally {
      setAuthLoading(false)
    }
  }

  const refreshEvidenceActivity = async () => {
    if (!token) return false
    try {
      const response = await authorizedFetch('/api/documents/relationships/map', token)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not refresh relationship evidence.')
      setRelationshipData(data)
      return true
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not refresh relationship evidence.')
      return false
    }
  }

  const handleAsk = async () => {
    if (!token || !question.trim()) return
    const response = await fetch('http://localhost:8000/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ question }),
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.detail || 'Could not generate an evidence-based answer.')
    }
    {
      setAnswer({
        text: data.answer?.text || 'Answer unavailable.',
        status: data.answer?.verification_status || 'Not Enough Evidence',
      })
      setEvidenceCards(
        (data.citations || []).map((item: Record<string, unknown>, index: number) => ({
          id: index,
          documentId: Number(item.document_id),
          title: String(item.document_name || 'Source document'),
          detail: `${String(item.source || 'Source')}${item.page ? ` · Page ${item.page}` : ''}`,
          snippet: String(item.quote || ''),
          status: String(item.support_status || 'Not Enough Evidence'),
          relevance: Math.round(Number(item.score) || 0),
        })),
      )
      setClaims(data.claims || [])
      setCoverage(data.evidence_coverage || null)
      setWhyResults(data.why_these_results || [])
      setConflicts(data.conflicts || [])
      setChangeEvents(data.change_events || [])
    }
    await refreshEvidenceActivity()
  }

  const runAsk = async () => {
    if (loading || !question.trim()) return
    setLoading(true)
    setAskError('')
    setAnswer({ text: 'Searching permitted source documents…', status: 'Not Enough Evidence' })
    setEvidenceCards([])
    setClaims([])
    setCoverage(null)
    try {
      await handleAsk()
    } catch (error) {
      setAskError(error instanceof Error ? error.message : 'Could not complete the evidence search.')
    } finally {
      setLoading(false)
    }
  }

  const compareSelectedVersions = async () => {
    if (!token || !selectedDocumentId) return
    try {
      const response = await authorizedFetch(`/api/documents/${selectedDocumentId}/compare`, token)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not compare document versions.')
      setVersionComparison(data)
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not compare document versions.')
    }
  }

  const viewEvidenceDocument = async (documentId: number) => {
    if (!token) return
    try {
      const response = await authorizedFetch(`/api/documents/${documentId}/chunks`, token)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not open this document evidence.')
      setDocumentEvidence(data)
      setOpenDocumentId(documentId)
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not open this document evidence.')
    }
  }

  const removeDocument = async (document: DocumentItem) => {
    if (!token || deletingDocumentIds.includes(document.id)) return
    if (!window.confirm(`Remove "${document.title}" from indexed sources? This hides it from search and records a deletion alert.`)) return
    setDeletingDocumentIds((ids) => [...ids, document.id])
    try {
      const response = await authorizedFetch(`/api/documents/${document.id}`, token, { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not remove this document.')
      setDocuments((items) => items.filter((item) => item.id !== document.id))
      await refreshEvidenceActivity()
      setSources((items) => items.map((source) => source.id === document.source_id
        ? { ...source, documents_count: Math.max(0, source.documents_count - 1) }
        : source))
      if (openDocumentId === document.id) {
        setOpenDocumentId(null)
        setDocumentEvidence([])
      }
      const alertsResponse = await authorizedFetch('/api/change-alerts', token)
      if (alertsResponse.ok) setChangeAlerts(await alertsResponse.json())
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not remove this document.')
    } finally {
      setDeletingDocumentIds((ids) => ids.filter((id) => id !== document.id))
    }
  }

  const resolveConflict = async (conflictId: number) => {
    if (!token) return
    const resolution = window.prompt('Explain how this conflict was resolved:')
    if (!resolution?.trim()) return
    try {
      const response = await authorizedFetch(`/api/conflicts/${conflictId}/review`, token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolution }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'You are not permitted to resolve this conflict.')
      setConflicts((items) => items.map((item) => item.id === conflictId ? { ...item, status: 'reviewed', summary: `${item.summary} Resolution: ${resolution.trim()}` } : item))
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not save the conflict resolution.')
    }
  }

  const reviewChangeAlert = async (alertId: number) => {
    if (!token) return
    try {
      const response = await authorizedFetch(`/api/change-alerts/${alertId}/review`, token, { method: 'POST' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'You are not permitted to review this alert.')
      setChangeAlerts((items) => items.map((item) => item.id === alertId ? { ...item, reviewed: true } : item))
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not review this alert.')
    }
  }

  const exportEvidenceReport = async (format: 'json' | 'csv') => {
    if (!token) return
    try {
      const response = await authorizedFetch(`/api/reports/export?format=${format}`, token)
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Report export is not permitted for this account.')
      }
      const reportBlob = await response.blob()
      const url = URL.createObjectURL(reportBlob)
      const download = document.createElement('a')
      download.href = url
      download.download = `evidence-report.${format}`
      download.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not export the evidence report.')
    }
  }

  const syncSource = async (sourceId: number) => {
    if (!token) return
    try {
      const response = await authorizedFetch(`/api/sources/${sourceId}/sync`, token, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Source synchronization failed.')
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Source synchronization failed.')
    }
  }

  const uploadSelectedFiles = async () => {
    if (!token || selectedFiles.length === 0 || uploading) return
    setUploading(true)
    setUploadMessage('')
    try {
      for (const file of selectedFiles) {
        const formData = new FormData()
        formData.append('file', file)
        const response = await authorizedFetch('/api/sources/files', token, { method: 'POST', body: formData })
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || `Could not upload ${file.name}.`)
      }
      setUploadMessage(`${selectedFiles.length} file(s) uploaded and indexed.`)
      setSelectedFiles([])
      const [sourceResponse, documentResponse, alertResponse] = await Promise.all([
        authorizedFetch('/api/sources', token),
        authorizedFetch('/api/documents', token),
        authorizedFetch('/api/change-alerts', token),
      ])
      if (sourceResponse.ok) setSources(await sourceResponse.json())
      if (documentResponse.ok) setDocuments(await documentResponse.json())
      if (alertResponse.ok) setChangeAlerts(await alertResponse.json())
      await refreshEvidenceActivity()
    } catch (error) {
      setUploadMessage(error instanceof Error ? error.message : 'Upload could not be completed.')
    } finally {
      setUploading(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('rag-token')
    setToken(null)
    setUser(null)
  }

  const deleteConversation = async (conversation: ConversationItem) => {
    if (!token || !window.confirm(`Delete search history for "${conversation.title}"?`)) return
    try {
      const response = await authorizedFetch(`/api/conversations/${conversation.id}`, token, { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not delete this history item.')
      setConversations((items) => items.filter((item) => item.id !== conversation.id))
      const deletedQueryIds = new Set(conversation.query_ids)
      setEvidenceReports((items) => items.filter((item) => !deletedQueryIds.has(item.query_id)))
      setSelectedReportId((selected) => deletedQueryIds.has(selected ?? -1)
        ? evidenceReports.find((item) => !deletedQueryIds.has(item.query_id))?.query_id ?? null
        : selected)
      setPageError('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Could not delete this history item.')
    }
  }

  const selectedEvidenceReport = evidenceReports.find((report) => report.query_id === selectedReportId) || null
  const filteredConversations = conversations.filter((conversation) => conversation.title.toLowerCase().includes(historySearch.trim().toLowerCase()))
  const relationshipSearchTerm = relationshipSearch.trim().toLowerCase()
  const relationshipRecordsById = new Map(relationshipData.nodes.map((record) => [record.id, record]))
  const relationshipEdgeTypes = Array.from(new Set(relationshipData.edges.map((edge) => edge.type))).sort()
  const filteredEvidenceActivity = relationshipData.edges.filter((edge) => {
    const record = relationshipRecordsById.get(edge.from)
    const relatedRecord = relationshipRecordsById.get(edge.to)
    const detailsText = Object.values(edge.details).flatMap((value) => Array.isArray(value) ? value : [value])
      .filter((value) => value !== null && value !== undefined)
      .join(' ')
    const rowText = `${edge.type} ${edge.explanation} ${record?.label ?? ''} ${relatedRecord?.label ?? ''} ${record?.type ?? ''} ${relatedRecord?.type ?? ''} ${detailsText}`.toLowerCase()
    return (relationshipEdgeFilter === 'all' || edge.type === relationshipEdgeFilter)
      && (!relationshipSearchTerm || rowText.includes(relationshipSearchTerm))
  }).flatMap((edge) => {
    const record = relationshipRecordsById.get(edge.from)
    const relatedRecord = relationshipRecordsById.get(edge.to)
    return record && relatedRecord ? [{ edge, record, relatedRecord }] : []
  })
  const reportClaims = selectedEvidenceReport?.claims || []
  const filteredReportClaims = reportClaims.filter((claim) => {
    const statusMatches = claimFilter === 'All claims' || claim.status === claimFilter
    const searchText = reportSearch.trim().toLowerCase()
    const searchMatches = !searchText || claim.text.toLowerCase().includes(searchText)
      || claim.evidence.some((evidence) => evidence.document_name.toLowerCase().includes(searchText))
    return statusMatches && searchMatches
  })
  const reportStatus = (() => {
    if (!selectedEvidenceReport || !reportClaims.length) return { label: 'Insufficient evidence', reason: 'No verified factual claims were saved for this answer.', tone: 'warning' }
    if (reportClaims.every((claim) => claim.status === 'Not verified')) return { label: 'Verification incomplete', reason: 'Evidence saved for this answer is not available to this account, so claim verification cannot be inspected.', tone: 'warning' }
    if (selectedEvidenceReport.conflicts.some((conflict) => conflict.status === 'open')) {
      return { label: 'Conflicting evidence', reason: 'Relevant retrieved sources disagree; no source has been assumed authoritative.', tone: 'conflict' }
    }
    const supported = reportClaims.filter((claim) => claim.status === 'Supported').length
    const partial = reportClaims.filter((claim) => claim.status === 'Partly Supported').length
    const unsupported = reportClaims.filter((claim) => ['Unsupported', 'Not Enough Evidence', 'Not verified'].includes(claim.status)).length
    if (supported === reportClaims.length) return { label: 'Well supported', reason: 'Every identified claim has supporting retrieved evidence and no recorded open conflict.', tone: 'success' }
    if (supported + partial > 0) return { label: 'Partially supported', reason: `${unsupported + partial} of ${reportClaims.length} claims remain incomplete or lack sufficient supporting evidence.`, tone: 'warning' }
    return { label: 'Insufficient evidence', reason: 'The retrieved evidence does not sufficiently support the identified claims.', tone: 'warning' }
  })()
  const reportEvidence = selectedEvidenceReport
    ? selectedEvidenceReport.claims.flatMap((claim) => claim.evidence.map((evidence) => ({ ...evidence, claimText: claim.text, claimStatus: claim.status })))
    : []
  const copyReportText = async (text: string, message: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setReportMessage(message)
    } catch {
      setReportError('Clipboard access is unavailable in this browser.')
    }
  }

  if (!user || !token) {
    return (
      <div className="login-shell">
        <div className="login-panel">
          <div className="login-header">
            <div className="brand-mark">E</div>
            <div>
              <p className="eyebrow">Enterprise</p>
              <h1>RAG Assistant</h1>
            </div>
          </div>
          <div className="signin-box">
            <h2>Sign in</h2>
            <div className="form-grid">
              <label>
                <span>Email</span>
                <input defaultValue="admin@company.com" id="email" type="email" />
              </label>
              <label>
                <span>Password</span>
                <input defaultValue="admin123" id="password" type="password" />
              </label>
            </div>
            {authError && <div className="error-text" role="alert">{authError}</div>}
            <button
              className="primary-btn"
              type="button"
              disabled={authLoading}
              aria-busy={authLoading}
              onClick={() => {
                const email = (document.getElementById('email') as HTMLInputElement)?.value
                const password = (document.getElementById('password') as HTMLInputElement)?.value
                void handleLogin(email, password)
              }}
            >
              {authLoading ? 'Signing in…' : 'Sign in'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark">E</div>
          <div>
            <div className="eyebrow">Enterprise</div>
            <div className="brand-name">RAG Assistant</div>
          </div>
        </div>

        <nav className="nav-menu">
          {navItems.filter(({ key }) => (
            (key !== 'users' || user.role.toLowerCase() === 'admin')
            && (key !== 'reports' || ['admin', 'manager'].includes(user.role.toLowerCase()))
          )).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={`nav-item ${currentPage === key ? 'active' : ''}`}
              onClick={() => setCurrentPage(key)}
              type="button"
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="user-bar">
          <div className="user-avatar">{user.name.charAt(0)}</div>
          <div>
            <div className="user-name">{user.name}</div>
            <div className="user-role">{user.role}</div>
          </div>
          <button type="button" className="tiny-btn" onClick={handleLogout}>
            <LogOut size={14} />
          </button>
        </div>
      </aside>

      <main className="main-panel">
        {pageError && <div className="error-text workspace-error" role="alert">{pageError}</div>}
        {currentPage === 'chat' && (
          <div className="content-stack">
            <div className="topbar">
              <div>
                <p className="eyebrow">Enterprise search</p>
                <h2>Question and answer</h2>
              </div>
              <button className="secondary-btn" type="button" onClick={() => {
                setQuestion('')
                setAnswer({ text: 'Ask a question to retrieve evidence from sources you are permitted to access.', status: 'Not Enough Evidence' })
                setEvidenceCards([])
                setClaims([])
                setCoverage(null)
                setAskError('')
              }}>
                New Chat
              </button>
            </div>

            <div className="answer-panel">
              <div className="status-row">
                <span className={`status-badge ${answer.status === 'Supported' ? 'success' : ['Not Enough Evidence', 'Unsupported'].includes(answer.status) ? 'warning' : 'conflict'}`}>{answer.status}</span>
                <span className="metric-small">Checked against retrieved evidence</span>
              </div>
              <h3>Answer</h3>
              <p className="answer-text">{answer.text}</p>
              {loading && <div className="generating-state" role="status" aria-live="polite">
                <span>Generating answer</span>
                <span className="loading-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span>
              </div>}
              {coverage && <div className="coverage-strip">
                <strong>Evidence Coverage</strong>
                <span>Supported {coverage.Supported ?? 0}</span>
                <span>Partly supported {coverage['Partly Supported'] ?? 0}</span>
                <span>Conflicting {coverage['Conflicting Information'] ?? 0}</span>
                <span>Unsupported {coverage.Unsupported ?? 0}</span>
                <span>Not enough evidence {coverage['Not Enough Evidence'] ?? 0}</span>
                <small>{String(coverage.coverage_percent ?? 0)}% · not a guarantee of correctness</small>
              </div>}
              {claims.length > 0 && <div className="claim-list">
                <strong>Answer Check</strong>
                {claims.map((claim, index) => <div className="claim-row" key={`${index}-${claim.claim}`}>
                  <span>{claim.claim}</span>
                  <span className="muted">{claim.support_status}</span>
                </div>)}
              </div>}
              {changeEvents.length > 0 && <div className="claim-list">
                <strong>Recorded source changes this month</strong>
                {changeEvents.map((event) => <div className="claim-row" key={event.id}>
                  <span>{event.document}: {event.summary}</span>
                  <span className="muted">{new Date(event.created_at).toLocaleDateString()}</span>
                </div>)}
              </div>}
              {askError && <div className="error-text" role="alert">{askError}</div>}
            </div>

            <div className="tool-row">
              <button className="ghost-btn" type="button" onClick={() => setShowWhyResults((value) => !value)}>
                <Search size={14} /> Why These Results?
              </button>
            </div>
            {showWhyResults && <div className="list-card">
              {whyResults.length ? whyResults.map((result, index) => <div className="result-explanation" key={`${result.document_name}-${index}`}>
                <strong>{result.document_name}</strong>
                <span>{result.source || 'Source'} · Relevance {result.relevance_score} · {result.document_date || 'Date unavailable'}</span>
                <span>Matched terms: {result.matched_keywords.join(', ') || 'No exact keyword matches'}</span>
              </div>) : <p className="muted">Ask a question to see actual retrieval signals.</p>}
            </div>}

            <div className="evidence-list">
              {evidenceCards.map((card) => (
                <div key={card.id} className="evidence-card">
                  <div className="evidence-header">
                    <div>
                      <strong>{card.title}</strong>
                      <div className="muted">{card.detail}</div>
                    </div>
                    <div className="relevance-box">{card.relevance}%</div>
                  </div>
                  <div className="snippet">“{card.snippet}”</div>
                  <div className="card-footer">
                    <span className={`status-badge ${card.status === 'Supported' ? 'success' : ['Not Enough Evidence', 'Unsupported'].includes(card.status) ? 'warning' : 'conflict'}`}>
                      {card.status}
                    </span>
                    <button type="button" className="ghost-btn" onClick={() => void viewEvidenceDocument(card.documentId)}>
                      View Document
                    </button>
                  </div>
                  {openDocumentId === card.documentId && <div className="document-evidence">
                    <strong>Source text</strong>
                    {documentEvidence.map((chunk) => <p key={chunk.id}>
                      {chunk.page_number ? `Page ${chunk.page_number} · ` : ''}{chunk.section_title ? `${chunk.section_title}: ` : ''}{chunk.content}
                    </p>)}
                  </div>}
                </div>
              ))}
            </div>

            <div className="composer">
              <div className="tool-row source-scope"><Search size={14} /><span>All sources you are permitted to access</span></div>
              <div className="composer-input-row">
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  rows={3}
                />
                <button type="button" className="primary-btn ask-btn" onClick={() => void runAsk()} disabled={loading || !question.trim()}>
                  {loading ? <><span>Generating</span><span className="loading-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span></> : 'Ask'}
                </button>
              </div>
            </div>
          </div>
        )}

        {currentPage === 'history' && (
          <div className="content-stack">
            <div className="topbar">
              <h2>Search History</h2>
            </div>
            <label htmlFor="history-search">Search previous questions</label>
            <input id="history-search" type="search" value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="Filter history" />
            <div className="list-card">
              {filteredConversations.length ? filteredConversations.map((conversation) => {
                const savedReport = evidenceReports.find((report) => report.query_id === conversation.latest_query_id)
                return <div className="list-row history-row" key={conversation.id}>
                  <div>
                    <strong>{conversation.title}</strong>
                    <small>{new Date(conversation.updated_at).toLocaleString()}</small>
                  </div>
                  <div className="tool-row">
                    <button type="button" className="ghost-btn" disabled={!savedReport} onClick={() => {
                      if (!savedReport) return
                      setSelectedReportId(savedReport.query_id)
                      setCurrentPage('reports')
                    }}>{savedReport ? 'Open saved result' : 'Saved result unavailable'}</button>
                    <button type="button" className="ghost-btn danger-action" onClick={() => void deleteConversation(conversation)}>Delete</button>
                  </div>
                </div>
              }) : <p className="muted">{conversations.length ? 'No history items match your search.' : 'No saved searches yet.'}</p>}
            </div>
          </div>
        )}

        {currentPage === 'sources' && (
          <div className="content-stack">
            <div className="topbar">
              <h2>Data Sources</h2>
            </div>
            <div className="source-grid">
              <div className="source-card">
                <h3>Upload Files</h3>
                <p>PDF, DOCX, TXT, Markdown, CSV, XLSX</p>
                <input type="file" multiple onChange={(event) => setSelectedFiles(Array.from(event.target.files || []))} />
                <button className="primary-btn" type="button" disabled={uploading || !selectedFiles.length} onClick={() => void uploadSelectedFiles()}>{uploading ? 'Uploading…' : 'Upload'}</button>
                {uploadMessage && <p className={uploadMessage.includes('could not') || uploadMessage.includes('Could not') ? 'error-text' : 'muted'} role="status">{uploadMessage}</p>}
              </div>
              <div className="source-card">
                <h3>Connect Database</h3>
                <p>MySQL · PostgreSQL · SQL Server</p>
                <button className="secondary-btn" type="button" disabled title="No database connector is configured">Setup required</button>
                <p className="muted">Database adapter and secure credential storage are not configured.</p>
              </div>
              <div className="source-card">
                <h3>Website / API</h3>
                <p>Authorized websites and REST endpoints</p>
                <button className="secondary-btn" type="button" disabled title="No website/API connector is configured">Setup required</button>
                <p className="muted">A crawler/API adapter must be configured before connecting.</p>
              </div>
              <div className="source-card">
                <h3>Cloud Storage</h3>
                <p>Google Drive · SharePoint · Amazon S3</p>
                <button className="secondary-btn" type="button" disabled title="Cloud OAuth credentials are not configured">Setup required</button>
                <p className="muted">Configure provider OAuth credentials to enable cloud sync.</p>
              </div>
            </div>
          </div>
        )}

        {currentPage === 'documents' && (
          <div className="content-stack">
            <div className="topbar"><h2>Documents</h2></div>
            <div className="list-card">
              {documents.length ? documents.map((document) => (
                <div key={document.id} className="list-row">
                  <span>{document.title} <small>{document.version || 'Version unknown'}</small></span>
                  <span>{document.status}</span>
                  {document.can_delete && <button
                    type="button"
                    className="ghost-btn danger-action"
                    disabled={deletingDocumentIds.includes(document.id)}
                    onClick={() => void removeDocument(document)}
                  >{deletingDocumentIds.includes(document.id) ? 'Removing…' : 'Remove'}</button>}
                </div>
              )) : <p className="muted">No indexed documents available to your account.</p>}
            </div>
          </div>
        )}

        {currentPage === 'conflicts' && (
          <div className="content-stack">
            <div className="topbar"><h2>Conflicts</h2></div>
            <div className="list-card">
              {conflicts.length ? conflicts.map((conflict) => <section className="feature-card" key={conflict.id}>
                <div className="evidence-header"><strong>{conflict.subject}</strong><span className={`status-badge ${conflict.status === 'open' ? 'warning' : 'success'}`}>{conflict.status}</span></div>
                <p>{conflict.summary}</p>
                <div className="conflict-evidence">
                  {conflict.evidence.map((item, index) => <div className="conflict-side" key={`${item.document_name}-${index}`}>
                    <strong>{item.document_name}{item.page ? ` · Page ${item.page}` : ''}</strong>
                    {item.values?.length ? <span>Values: {item.values.join(', ')}</span> : null}
                    <p>{item.quote}</p>
                  </div>)}
                </div>
                {conflict.status === 'open' && ['admin', 'manager'].includes(user.role.toLowerCase()) && <button className="secondary-btn" type="button" onClick={() => void resolveConflict(conflict.id)}>Review and resolve</button>}
              </section>) : <p className="muted">No recorded conflicts are available to your account.</p>}
            </div>
          </div>
        )}

        {currentPage === 'alerts' && (
          <div className="content-stack">
            <div className="topbar"><h2>Change Alerts</h2><span className="muted">Upload changes and deletions are tracked. External sync needs a configured connector.</span></div>
            <div className="list-card">
              {changeAlerts.length ? changeAlerts.map((alert) => <div className="feature-card" key={alert.id}>
                <div className="evidence-header"><strong>{alert.document}</strong><span className="status-badge warning">{alert.event_type}</span></div>
                <p>{alert.summary}</p>
                <div className="card-footer"><small className="muted">{new Date(alert.created_at).toLocaleString()}</small>
                  {!alert.reviewed && ['admin', 'manager'].includes(user.role.toLowerCase()) && <button className="ghost-btn" type="button" onClick={() => void reviewChangeAlert(alert.id)}>Mark reviewed</button>}
                  {alert.reviewed && <span className="muted">Reviewed</span>}
                </div>
              </div>) : <p className="muted">No document change alerts recorded.</p>}
            </div>
            <h3>Sources and last successful sync</h3>
            <div className="list-card">{sources.map((source) => <div className="list-row" key={source.id}>
              <span>{source.name}</span><span>{source.last_sync_at ? new Date(source.last_sync_at).toLocaleString() : 'No successful sync'}</span>
              {['admin', 'manager'].includes(user.role.toLowerCase()) && <button className="ghost-btn" type="button" onClick={() => void syncSource(source.id)}>Refresh</button>}
            </div>)}</div>
          </div>
        )}

        {currentPage === 'versions' && (
          <div className="content-stack">
            <div className="topbar"><h2>Compare Versions</h2></div>
            <div className="list-card">
              <label htmlFor="version-document">Document</label>
              <select id="version-document" value={selectedDocumentId} onChange={(event) => setSelectedDocumentId(event.target.value)}>
                <option value="">Choose a document</option>
                {documents.map((document) => <option key={document.id} value={document.id}>{document.title} ({document.version || 'version unknown'})</option>)}
              </select>
              <button type="button" className="secondary-btn" disabled={!selectedDocumentId} onClick={() => void compareSelectedVersions()}>Compare with previous version</button>
              {versionComparison && <>
                <p>Current: {versionComparison.current_version || 'unknown'} · Previous: {versionComparison.previous_version || 'none'}</p>
                {versionComparison.message && <p className="muted">{versionComparison.message}</p>}
                {versionComparison.changes?.map((change, index) => <div className={`diff-row diff-${change.type}`} key={index}>
                  <strong>{change.type}</strong>
                  {change.previous.map((line, lineIndex) => <div key={`old-${lineIndex}`}>− {line}</div>)}
                  {change.current.map((line, lineIndex) => <div key={`new-${lineIndex}`}>+ {line}</div>)}
                </div>)}
              </>}
            </div>
          </div>
        )}

        {currentPage === 'coverage' && (
          <div className="content-stack">
            <div className="topbar"><h2>Evidence Coverage</h2></div>
            {coverageSummary ? <>
              <div className="stats-grid">
                {Object.entries(coverageSummary.claims).filter(([key]) => key !== 'total').map(([label, value]) => <div className="stat-box" key={label}><label>{label}</label><strong>{value}</strong></div>)}
              </div>
              <p className="muted">{coverageSummary.coverage_disclaimer}</p>
            </> : <p className="muted">Coverage information is not available for this account.</p>}
          </div>
        )}

        {currentPage === 'relationships' && (
          <div className="content-stack">
            <div className="topbar"><h2>Evidence Activity</h2></div>
            <p className="muted">A table of saved questions, claims, cited evidence, document versions, and recorded conflicts. Each row reflects stored records; it does not infer source authority.</p>
            <p className="muted relationship-basis">{relationshipData.basis}</p>
            {relationshipData.truncated && <p className="muted">This table is limited to recent records. Search or filter by activity type to narrow the results.</p>}
            <div className="relationship-controls">
              <label className="relationship-search"><Search size={16} aria-hidden="true" /><input aria-label="Search evidence activity" value={relationshipSearch} onChange={(event) => setRelationshipSearch(event.target.value)} placeholder="Search questions, claims, source names, evidence, or IDs" /></label>
              <label>Activity type<select value={relationshipEdgeFilter} onChange={(event) => setRelationshipEdgeFilter(event.target.value)}>
                <option value="all">All activity</option>
                {relationshipEdgeTypes.map((type) => <option key={type} value={type}>{type}</option>)}
              </select></label>
              <span className="muted">{filteredEvidenceActivity.length} records</span>
            </div>
            {filteredEvidenceActivity.length ? <div className="list-card evidence-activity-table-wrap">
              <table className="evidence-activity-table">
                <thead><tr>
                  <th scope="col">What happened</th>
                  <th scope="col">Record</th>
                  <th scope="col">Related record</th>
                  <th scope="col">Source / evidence</th>
                  <th scope="col">Status</th>
                  <th scope="col">Action</th>
                </tr></thead>
                <tbody>{filteredEvidenceActivity.map(({ edge, record, relatedRecord }) => {
                  const sourceRecord = [record, relatedRecord].find((item) => item.type === 'document' || item.type === 'document version')
                  const evidenceRecord = [record, relatedRecord].find((item) => item.type === 'evidence')
                  const documentId = Number(sourceRecord?.details.document_id ?? evidenceRecord?.details.document_id ?? 0)
                  const sourceName = sourceRecord?.details.source_name
                  const filename = sourceRecord?.details.filename
                  const version = sourceRecord?.details.version ?? evidenceRecord?.details.version
                  const evidenceQuote = evidenceRecord?.details.quote
                  const statusValue = evidenceRecord?.details.status ?? sourceRecord?.details.status ?? record.details.status ?? relatedRecord.details.status
                  const displayedQuote = typeof evidenceQuote === 'string' ? evidenceQuote : ''
                  return <tr key={edge.id}>
                    <td><strong>{edge.type}</strong>{edge.candidate && <span className="status-badge warning">Candidate</span>}<small>{edge.explanation}</small>{Array.isArray(edge.details.shared_terms) && <small>Shared terms: {edge.details.shared_terms.join(', ')}</small>}</td>
                    <td><span className="activity-record-type">{record.type}</span><strong>{record.label}</strong></td>
                    <td><span className="activity-record-type">{relatedRecord.type}</span><strong>{relatedRecord.label}</strong></td>
                    <td>
                      {sourceName && <small>Source: {sourceName}</small>}
                      {filename && <small>Filename: {filename}</small>}
                      {version && <small>Version: {version}</small>}
                      {evidenceRecord?.details.page && <small>Page: {evidenceRecord.details.page}</small>}
                      {displayedQuote && <blockquote>{displayedQuote.length > 240 ? `${displayedQuote.slice(0, 240)}…` : displayedQuote}</blockquote>}
                      {!sourceName && !filename && !version && !displayedQuote && <span className="muted">No source passage linked to this row.</span>}
                    </td>
                    <td>{statusValue ? <span className="status-badge">{String(statusValue)}</span> : '—'}</td>
                    <td>{documentId > 0 && <button type="button" className="ghost-btn" onClick={() => void viewEvidenceDocument(documentId)}>Open authorized evidence</button>}{(record.type === 'conflict' || relatedRecord.type === 'conflict') && <button type="button" className="ghost-btn" onClick={() => setCurrentPage('conflicts')}>View conflict</button>}</td>
                  </tr>
                })}</tbody>
              </table>
            </div> : <div className="list-card">
              <strong>No evidence activity matches.</strong>
              <p className="muted">{relationshipData.edges.length ? 'Try a different search or activity filter.' : 'Ask questions about accessible documents or upload files to create actual evidence activity records.'}</p>
            </div>}
            {openDocumentId !== null && <div className="list-card document-evidence">
              <strong>{documents.find((document) => document.id === openDocumentId)?.title || 'Document evidence'}</strong>
              {documentEvidence.map((chunk) => <p key={chunk.id}>
                {chunk.page_number ? `Page ${chunk.page_number} · ` : ''}{chunk.section_title ? `${chunk.section_title}: ` : ''}{chunk.content}
              </p>)}
            </div>}
          </div>
        )}

        {currentPage === 'reports' && (
          <div className="content-stack">
            <div className="topbar"><h2>Evidence Reports</h2>
              <div className="tool-row report-actions">
                <button className="secondary-btn" type="button" onClick={() => void exportEvidenceReport('json')}>Export JSON</button>
                <button className="secondary-btn" type="button" onClick={() => void exportEvidenceReport('csv')}>Export CSV</button>
                <button className="secondary-btn" type="button" onClick={() => window.print()}>Print / PDF</button>
              </div>
            </div>
            {reportError && <div className="error-text" role="alert">{reportError}</div>}
            {reportLoading ? <div className="list-card" role="status">Loading evidence reports…</div> : evidenceReports.length ? <>
              <div className="report-picker list-card">
                <label htmlFor="evidence-report-select">Select a saved answer</label>
                <select id="evidence-report-select" value={selectedReportId ?? ''} onChange={(event) => {
                  setSelectedReportId(Number(event.target.value))
                  setReportSearch('')
                  setClaimFilter('All claims')
                  setExplainedClaimId(null)
                  setReportMessage('')
                }}>
                  {evidenceReports.map((report) => <option key={report.query_id} value={report.query_id}>
                    {new Date(report.created_at).toLocaleString()} — {report.question.slice(0, 90)}
                  </option>)}
                </select>
              </div>
              {selectedEvidenceReport && <>
                <section className="feature-card evidence-report-header">
                  <div className={`report-status report-status-${reportStatus.tone}`} role="status">
                    <strong><span aria-hidden="true">{reportStatus.tone === 'success' ? '✓' : reportStatus.tone === 'conflict' ? '⚠' : '!'}</span> {reportStatus.label}</strong>
                    <span>{reportStatus.reason}</span>
                  </div>
                  <div className="report-meta-grid">
                    <div><small>Original question</small><strong>{selectedEvidenceReport.question}</strong></div>
                    <div><small>Report generated</small><strong>{new Date(selectedEvidenceReport.created_at).toLocaleString()}</strong></div>
                    <div><small>Sources examined</small><strong>{selectedEvidenceReport.sources_examined}</strong></div>
                    <div><small>Supporting evidence</small><strong>{reportEvidence.filter((item) => item.claimStatus === 'Supported' || item.claimStatus === 'Partly Supported').length}</strong></div>
                    <div><small>Conflicting evidence</small><strong>{selectedEvidenceReport.conflicts.reduce((sum, conflict) => sum + conflict.evidence.length, 0)}</strong></div>
                    <div><small>Unsupported / unresolved claims</small><strong>{reportClaims.filter((claim) => ['Unsupported', 'Not Enough Evidence', 'Partly Supported', 'Conflicting Information'].includes(claim.status)).length}</strong></div>
                  </div>
                  <div>
                    <h3>Answer</h3>
                    <p className="answer-text">{selectedEvidenceReport.answer}</p>
                  </div>
                  <div className="tool-row">
                    <button type="button" className="ghost-btn" onClick={() => void copyReportText(`${selectedEvidenceReport.question}\n\n${selectedEvidenceReport.answer}`, 'Answer and question copied.')}>Copy answer</button>
                    <button type="button" className="ghost-btn" onClick={() => void copyReportText(JSON.stringify(selectedEvidenceReport, null, 2), 'Selected report details copied as JSON.')}>Copy claim summary</button>
                  </div>
                </section>

                <section className="list-card">
                  <div className="evidence-header"><h3>How much of this answer is verified?</h3><span className="muted">{reportClaims.length} factual claims</span></div>
                  <div className="coverage-segments" role="group" aria-label="Filter claims by evidence status">
                    {[
                      ['Supported', 'Supported'],
                      ['Partly Supported', 'Partially supported'],
                      ['Conflicting Information', 'Conflicting'],
                      ['Unsupported', 'Unsupported'],
                      ['Not Enough Evidence', 'Not enough evidence'],
                      ['Not verified', 'Not verified'],
                    ].map(([status, label]) => {
                      const count = reportClaims.filter((claim) => claim.status === status).length
                      return <button
                        key={status}
                        type="button"
                        className={`coverage-segment coverage-${status === 'Supported' ? 'supported' : status === 'Partly Supported' ? 'partial' : status === 'Conflicting Information' ? 'conflicting' : 'unsupported'} ${claimFilter === status ? 'selected' : ''}`}
                        onClick={() => setClaimFilter(claimFilter === status ? 'All claims' : status)}
                        aria-pressed={claimFilter === status}
                      >{label}: {count}</button>
                    })}
                  </div>
                  <p className="muted">Coverage is calculated from saved claim checks. It is not a measure or guarantee of answer correctness.</p>
                </section>

                <section className="list-card">
                  <div className="evidence-header"><h3>What makes up this answer?</h3><span className="muted">{filteredReportClaims.length} shown</span></div>
                  <div className="report-filters">
                    <label htmlFor="report-claim-search">Search claims and documents</label>
                    <input id="report-claim-search" type="search" value={reportSearch} onChange={(event) => setReportSearch(event.target.value)} placeholder="Find a claim or source" />
                  </div>
                  {filteredReportClaims.length ? filteredReportClaims.map((claim, index) => {
                    const claimConflicts = claim.status === 'Conflicting Information' ? selectedEvidenceReport.conflicts : []
                    const supporting = claim.evidence.filter((item) => ['Supported', 'Partly Supported'].includes(item.status))
                    return <details className="report-claim" key={claim.id}>
                      <summary>
                        <span><strong>Claim {reportClaims.indexOf(claim) + 1}:</strong> {claim.text}</span>
                        <span className={`status-badge ${claim.status === 'Supported' ? 'success' : claim.status === 'Conflicting Information' ? 'conflict' : 'warning'}`}>{claim.status === 'Partly Supported' ? 'Partially supported' : claim.status}</span>
                      </summary>
                      <div className="claim-report-detail">
                        <p>Supporting evidence: {supporting.length} · Contradicting evidence: {claimConflicts.reduce((sum, conflict) => sum + conflict.evidence.length, 0)}</p>
                        {claim.limitation && <p className="muted">{claim.limitation}</p>}
                        {!claim.evidence.length && <p className="muted">No accessible supporting quotation was saved for this claim.</p>}
                        {claim.evidence.map((item) => <article className="report-evidence-item" key={item.id}>
                          <div className="evidence-header"><strong>{item.document_name}</strong><span className="muted">{item.status}</span></div>
                          <blockquote>{item.quote || 'Quotation not available.'}</blockquote>
                          <p className="muted">Source: {item.source_name} · Type: {item.source_type || 'Not available'} · Page: {item.page ?? 'Not available'} · Section: {item.section || 'Not available'} · Version: {item.version || 'Not available'}</p>
                          <p className="muted">Created: {item.created_at ? new Date(item.created_at).toLocaleDateString() : 'Not available'} · Modified: {item.updated_at ? new Date(item.updated_at).toLocaleDateString() : 'Not available'}</p>
                          <div className="tool-row">
                            {item.document_id !== null && <button className="ghost-btn" type="button" onClick={() => void viewEvidenceDocument(item.document_id!)}>Open source</button>}
                            <button className="ghost-btn" type="button" onClick={() => void copyReportText(`${item.document_name}: “${item.quote}”`, 'Citation copied.')}>Copy citation</button>
                          </div>
                        </article>)}
                        <button type="button" className="secondary-btn" onClick={() => setExplainedClaimId(explainedClaimId === claim.id ? null : claim.id)}>
                          {explainedClaimId === claim.id ? 'Hide simple explanation' : 'Explain simply'}
                        </button>
                        {explainedClaimId === claim.id && <div className="simple-explanation">
                          <p><strong>What the source says:</strong> {claim.evidence[0]?.quote || 'No supporting quotation is available.'}</p>
                          <p><strong>Why it matters:</strong> {claim.evidence.length ? `This retrieved quotation is recorded against the claim: “${claim.text}”` : 'No retrieved source is recorded as supporting this claim.'}</p>
                          <p><strong>What it does not prove:</strong> {claim.status === 'Supported' ? 'Term matching does not establish semantic entailment or source authority.' : 'The available evidence does not fully establish this claim.'}</p>
                        </div>}
                        {index === 0 && claimConflicts.length > 0 && <p className="muted">This claim has a query-level recorded conflict below; the data does not map individual conflict passages to a specific claim.</p>}
                      </div>
                    </details>
                  }) : <p className="muted">No claims match the selected filter.</p>}
                </section>

                <section className="list-card">
                  <h3>Evidence Side by Side</h3>
                  <div className="report-comparison">
                    <div className="report-evidence-column">
                      <h4>Supporting evidence</h4>
                      {reportEvidence.filter((item) => ['Supported', 'Partly Supported'].includes(item.claimStatus)).map((item) => <article className="report-evidence-item" key={`support-${item.id}`}>
                        <strong>{item.document_name}</strong><blockquote>{item.quote}</blockquote><small>Supports recorded claim: {item.claimText}</small>
                      </article>)}
                      {!reportEvidence.some((item) => ['Supported', 'Partly Supported'].includes(item.claimStatus)) && <p className="muted">No supporting citations were saved.</p>}
                    </div>
                    <div className="report-evidence-column conflict-column">
                      <h4>Contradicting / conflicting evidence</h4>
                      {selectedEvidenceReport.conflicts.flatMap((conflict) => conflict.evidence.map((evidence, index) => <article className="report-evidence-item" key={`conflict-${conflict.id}-${index}`}>
                        <strong>{evidence.document_name}</strong>
                        {Array.isArray(evidence.values) && <p>Values: {evidence.values.join(' vs ')}</p>}
                        <blockquote>{evidence.quote || 'Quotation not available.'}</blockquote>
                        <small>{String(evidence.source || 'Source not available')} · Page: {evidence.page ?? 'Not available'} · Version: {evidence.version || 'Not available'}</small>
                        <p className="muted">{conflict.summary} · {conflict.status === 'open' ? 'Unresolved' : `Reviewed: ${conflict.resolution || 'Explanation not available'}`}</p>
                      </article>))}
                      {!selectedEvidenceReport.conflicts.length && <p className="muted">No recorded conflicting source values for this answer.</p>}
                    </div>
                  </div>
                </section>

                <section className="list-card">
                  <h3>Can I rely on these sources?</h3>
                  <p className="muted">Authority and freshness approval rules are not stored by this application. Dates below are shown as metadata only; newer does not mean more authoritative.</p>
                  {Array.from(new Map(reportEvidence.map((item) => [item.source_id, item])).values()).map((item) => <div className="source-reliability-row" key={item.source_id}>
                    <strong>{item.source_name} · {item.document_name}</strong>
                    <span>Authority: Not available (approval metadata not stored)</span>
                    <span>Freshness: {item.updated_at ? `Last modified ${new Date(item.updated_at).toLocaleDateString()}; applicability not assessed` : 'Not available'}</span>
                    <span>Relevance: Retrieved for “{item.claimText}”</span>
                    <span>Verification: {item.claimStatus}</span>
                  </div>)}
                  {!reportEvidence.length && <p className="muted">No accessible source metadata is available for this answer.</p>}
                </section>

                {selectedEvidenceReport.conflicts.length > 0 && <section className="list-card">
                  <h3>What changed, and why do sources disagree?</h3>
                  {selectedEvidenceReport.conflicts.map((conflict) => <article className="report-conflict" key={conflict.id}>
                    <div className="evidence-header"><strong>{conflict.subject}</strong><span className={`status-badge ${conflict.status === 'open' ? 'conflict' : 'success'}`}>{conflict.status === 'open' ? 'Unresolved' : 'Reviewed'}</span></div>
                    <p>{conflict.summary}</p>
                    {conflict.resolution && <p>Recorded review explanation: {conflict.resolution}</p>}
                    <div className="conflict-timeline">{[...conflict.evidence].sort((a, b) => String(a.document_updated_at || '').localeCompare(String(b.document_updated_at || ''))).map((evidence, index) => <div key={`${conflict.id}-${index}`} className="timeline-entry">
                      <strong>{evidence.document_updated_at ? new Date(String(evidence.document_updated_at)).toLocaleDateString() : 'Date not available'} · {evidence.document_name}</strong>
                      <span>Version: {evidence.version || 'Not available'} · {Array.isArray(evidence.values) ? evidence.values.join(', ') : 'Conflicting value not available'}</span>
                      <p>{evidence.quote || 'Quotation not available.'}</p>
                    </div>)}</div>
                    {conflict.status === 'open' && <p className="muted">Unresolved: confirm the applicable source, date, or policy scope before relying on either value.</p>}
                  </article>)}
                </section>}

                <section className="list-card">
                  <h3>What should I check next?</h3>
                  {reportClaims.filter((claim) => claim.status !== 'Supported').map((claim) => <div className="next-step-row" key={`next-${claim.id}`}>
                    <strong>{claim.text}</strong>
                    <p>{claim.status === 'Conflicting Information'
                      ? 'Ask the authorized source owner to confirm which record applies and document the reason.'
                      : claim.evidence.length
                        ? 'Check that the cited source is current, approved, and within scope for this question.'
                        : 'Upload or request access to a relevant source document, then ask this question again.'}</p>
                  </div>)}
                  {!reportClaims.some((claim) => claim.status !== 'Supported') && <p className="muted">No evidence gaps were identified by the saved claim checks. This does not guarantee answer correctness.</p>}
                </section>

                <section className="list-card">
                  <h3>Evidence Map</h3>
                  <p className="muted">Connections below are only saved claim-to-citation references.</p>
                  <div className="evidence-map">
                    {selectedEvidenceReport.claims.map((claim) => <div className="evidence-map-row" key={`map-${claim.id}`}>
                      <span className="evidence-map-claim">{claim.text}</span><span aria-hidden="true">→</span>
                      <div>{claim.evidence.length ? claim.evidence.map((item) => <button type="button" className="evidence-map-source" key={item.id} onClick={() => item.document_id !== null && void viewEvidenceDocument(item.document_id)}>
                        {item.document_name} · {item.status}
                      </button>) : <span className="muted">No linked evidence</span>}</div>
                    </div>)}
                  </div>
                </section>
                {openDocumentId !== null && <div className="list-card document-evidence">
                  <strong>{documents.find((document) => document.id === openDocumentId)?.title || 'Document evidence'}</strong>
                  {documentEvidence.map((chunk) => <p key={chunk.id}>{chunk.page_number ? `Page ${chunk.page_number} · ` : ''}{chunk.section_title ? `${chunk.section_title}: ` : ''}{chunk.content}</p>)}
                </div>}
                {reportMessage && <p className="report-message" role="status">{reportMessage}</p>}
                {coverageSummary && <p className="muted">{coverageSummary.coverage_disclaimer}</p>}
              </>}
            </> : <div className="list-card">{reportError ? 'Evidence reports could not be loaded.' : 'No saved answers are available for this account yet. Ask a question to create an evidence report.'}</div>}
            <div className="stats-grid report-summary-stats">
              <div className="stat-box"><label>Connected sources</label><strong>{reports.connected_sources}</strong></div>
              <div className="stat-box"><label>Ready documents</label><strong>{reports.ready_documents}</strong></div>
              <div className="stat-box"><label>Failed jobs</label><strong>{reports.failed_processing_jobs}</strong></div>
              <div className="stat-box"><label>Questions asked</label><strong>{reports.questions_asked}</strong></div>
            </div>
          </div>
        )}

        {currentPage === 'users' && (
          <div className="content-stack">
            <div className="topbar"><h2>User Management</h2></div>
            <div className="list-card">
              {managedUsers.length ? managedUsers.map((managedUser) => <div className="list-row" key={managedUser.id}>
                <span>{managedUser.name}<small>{managedUser.email}</small></span><span>{managedUser.role} · {managedUser.status}</span>
              </div>) : <p className="muted">No users were returned by the backend.</p>}
            </div>
          </div>
        )}

        {currentPage === 'settings' && (
          <div className="content-stack">
            <div className="topbar"><h2>Settings</h2></div>
            {runtimeSettings ? <div className="settings-box">
              <div className="settings-row"><strong>Answer generation</strong><span>{runtimeSettings.llm.provider} · {runtimeSettings.llm.status.replaceAll('_', ' ')} · Credentials configured: {runtimeSettings.llm.credentials_configured ? 'Yes' : 'No'}{runtimeSettings.llm.model ? ` · ${runtimeSettings.llm.model}` : ''}{runtimeSettings.llm.endpoint_host ? ` · ${runtimeSettings.llm.endpoint_host}` : ''}. {runtimeSettings.llm.diagnostic}</span></div>
              <div className="settings-row"><strong>Embeddings</strong><span>{runtimeSettings.embeddings.provider} · {runtimeSettings.embeddings.status.replaceAll('_', ' ')}{runtimeSettings.embeddings.model ? ` · ${runtimeSettings.embeddings.model}` : ''}. {runtimeSettings.embeddings.diagnostic}</span></div>
              <div className="settings-row"><strong>Retrieval</strong><span>{runtimeSettings.retrieval.method.replaceAll('_', ' ')} · Up to {runtimeSettings.retrieval.maximum_results} retrieved passages.</span></div>
              <div className="settings-row"><strong>File upload</strong><span>{runtimeSettings.source_connectors.file_upload}</span></div>
              <div className="settings-row"><strong>Database connector</strong><span>Unavailable · no database connector is implemented.</span></div>
              <div className="settings-row"><strong>Website / API connector</strong><span>Unavailable · no website or API ingestion connector is implemented.</span></div>
              <div className="settings-row"><strong>Cloud storage</strong><span>Unavailable · no cloud storage connector is implemented.</span></div>
              <div className="settings-row"><strong>Credentials</strong><span>Provider secrets are backend-only and are never returned by this status endpoint.</span></div>
            </div> : <div className="list-card" role="status">Runtime settings are loading or unavailable. Refresh the page to retry.</div>}
          </div>
        )}
      </main>
    </div>
  )
}

export default App
