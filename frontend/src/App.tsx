import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from "react-oidc-context";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileText,
  Gauge,
  LayoutDashboard,
  Search,
  ShieldCheck,
  UploadCloud,
  XCircle,
} from 'lucide-react';
import {
  ApiDocument,
  ApiDocumentStatus,
  getDocument,
  listDocuments,
  setAccessToken,
  uploadDocument,
} from './api';

type Page = 'dashboard' | 'documents' | 'monitoring' | 'details';
type DisplayStatus = 'Completed' | 'Processing' | 'Failed' | 'Uploaded';

const navItems = [
  { page: 'dashboard' as const, label: 'Dashboard', icon: LayoutDashboard },
  { page: 'documents' as const, label: 'Documents', icon: FileText },
  { page: 'monitoring' as const, label: 'Monitoring', icon: Gauge },
];

function displayStatus(status: ApiDocumentStatus): DisplayStatus {
  const values: Record<ApiDocumentStatus, DisplayStatus> = {
    UPLOADED: 'Uploaded',
    PROCESSING: 'Processing',
    COMPLETED: 'Completed',
    FAILED: 'Failed',
  };
  return values[status];
}

function StatusBadge({ status }: { status: ApiDocumentStatus }) {
  const label = displayStatus(status);
  const icon = status === 'COMPLETED'
    ? <CheckCircle2 size={14} />
    : status === 'FAILED'
      ? <XCircle size={14} />
      : <Activity size={14} />;

  return <span className={`status status-${label.toLowerCase()}`}>{icon}{label}</span>;
}

function formatUploaded(dateValue: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(dateValue));
}

function formatProcessingTime(milliseconds: number | null): string {
  return milliseconds == null ? '—' : `${(milliseconds / 1000).toFixed(1)} s`;
}

function App() {

  const auth = useAuth();

  const signOutRedirect = () => {
  const clientId = '3pd6tem71q5vf35cbn3rqchhpt';
  const logoutUri = 'http://localhost:5173';
  const cognitoDomain =
    'https://eu-central-1t23sf3gb5.auth.eu-central-1.amazoncognito.com';

  void auth.removeUser();

  window.location.href =
    `${cognitoDomain}/logout` +
    `?client_id=${clientId}` +
    `&logout_uri=${encodeURIComponent(logoutUri)}`;
};

    useEffect(() => {
    setAccessToken(
      auth.user?.access_token ?? null,
    );
  }, [auth.user?.access_token]);


  const [page, setPage] = useState<Page>('dashboard');
  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<ApiDocument | null>(null);
  const [query, setQuery] = useState('');
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const items = await listDocuments();
      setDocuments(items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load documents.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (
      !auth.isAuthenticated ||
      !auth.user?.access_token
    ) {
      return;
    }

    void loadDocuments();
  }, [
    auth.isAuthenticated,
    auth.user?.access_token,
    loadDocuments,
  ]);

  useEffect(() => {
    const hasActiveDocuments = documents.some((doc) =>
      doc.status === 'UPLOADED' || doc.status === 'PROCESSING',
    );
    if (!hasActiveDocuments) return;

    const timer = window.setInterval(() => {
      void loadDocuments();
    }, 2000);

    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  useEffect(() => {
    if (!selectedDocument || (selectedDocument.status !== 'UPLOADED' && selectedDocument.status !== 'PROCESSING')) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const freshDocument = await getDocument(selectedDocument.id);
        setSelectedDocument(freshDocument);
        setDocuments((current) => current.map((doc) =>
          doc.id === freshDocument.id ? freshDocument : doc,
        ));
        if (freshDocument.status === 'COMPLETED' || freshDocument.status === 'FAILED') {
          window.clearInterval(timer);
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'Unable to refresh document.');
      }
    }, 1500);

    return () => window.clearInterval(timer);
  }, [selectedDocument?.id, selectedDocument?.status]);

  const stats = useMemo(() => ({
    total: documents.length,
    completed: documents.filter((doc) => doc.status === 'COMPLETED').length,
    failed: documents.filter((doc) => doc.status === 'FAILED').length,
  }), [documents]);

  const filteredDocuments = documents.filter((doc) =>
    `${doc.filename} ${doc.document_type ?? ''} ${doc.status}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length || uploading) return;

    setUploading(true);
    setError(null);
    try {
      const created = await uploadDocument(files[0]);
      setDocuments((current) => [created, ...current.filter((doc) => doc.id !== created.id)]);
      setSelectedDocument(created);
      setPage('details');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Upload failed.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const openDocument = async (doc: ApiDocument) => {
    setSelectedDocument(doc);
    setPage('details');
    try {
      const fullDocument = await getDocument(doc.id);
      setSelectedDocument(fullDocument);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to open document.');
    }
  };

    if (auth.isLoading) {
    return (
      <div className="app-shell">
        <main className="main-content">
          <h2>Loading authentication...</h2>
        </main>
      </div>
    );
  }

  if (auth.error) {
    return (
      <div className="app-shell">
        <main className="main-content">
          <h2>Authentication Error</h2>
          <p>{auth.error.message}</p>
        </main>
      </div>
    );
  }

  
if (!auth.isAuthenticated) {
  return (
    <main className="login-page">
      <section className="login-hero">
        <div className="login-brand">
          <div className="brand-mark">M</div>
          <strong>MedFlow AI</strong>
        </div>

        <div className="login-copy">
          <p className="login-eyebrow">
            AI-POWERED DOCUMENT INTELLIGENCE
          </p>

          <h1>
            Scan medical documents.
            <span> Get structured reports in seconds.</span>
          </h1>

          <p className="login-description">
            Upload medical documents, extract text with OCR, and
            generate clear summaries and structured insights using
            a secure AWS-powered processing pipeline.
          </p>

          <div className="login-features">
            <div>
              <UploadCloud size={22} />
              <span>
                <strong>Upload securely</strong>
                PDF, PNG and JPG documents
              </span>
            </div>

            <div>
              <FileText size={22} />
              <span>
                <strong>Automatic OCR</strong>
                Extract readable text instantly
              </span>
            </div>

            <div>
              <Activity size={22} />
              <span>
                <strong>AI analysis</strong>
                Summaries and structured results
              </span>
            </div>
          </div>
        </div>

        <p className="login-disclaimer">
          Demo environment. Use synthetic or non-sensitive data only.
        </p>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-icon">
            <ShieldCheck size={30} />
          </div>

          <p className="login-eyebrow">SECURE ACCESS</p>
          <h2>Welcome to MedFlow AI</h2>

          <p>
            Sign in to upload documents, track processing progress,
            and review AI-generated reports.
          </p>

          <button
            type="button"
            className="login-button"
            onClick={() => void auth.signinRedirect()}
          >
            Continue with secure sign in
            <ChevronRight size={19} />
          </button>

          <div className="login-security">
            <ShieldCheck size={16} />
            Authentication powered by Amazon Cognito
          </div>
        </div>
      </section>
    </main>
  );
}




  return (
  
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div><strong>MedFlow AI</strong><span>Clinical document intelligence</span></div>
        </div>

        <nav>
          {navItems.map(({ page: target, label, icon: Icon }) => (
            <button key={target} className={page === target ? 'nav-item active' : 'nav-item'} onClick={() => setPage(target)}>
              <Icon size={19} />{label}
            </button>
          ))}
        </nav>

        <div className="sidebar-card">
          <ShieldCheck size={20} />
          <div><strong>Demo environment</strong><span>Use synthetic data only.</span></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">AI WORKFLOW DEMO</p>
            <h1>{page === 'dashboard' ? 'Medical Document Processing' : page === 'documents' ? 'Document History' : page === 'monitoring' ? 'System Monitoring' : 'Document Analysis'}</h1>
          </div>
          <div className="profile">
            <span>
              {String(auth.user?.profile.email ?? 'U')
                .charAt(0)
                .toUpperCase()}
            </span>

            <div>
              <strong>
                {String(auth.user?.profile.email ?? 'Signed-in user')}
              </strong>
              <small>Authenticated with Cognito</small>
            </div>

            <button
              type="button"
              className="text-button"
              onClick={signOutRedirect}
            >
              Sign out
            </button>
          </div>
        </header>

        {error && <div className="notice"><AlertTriangle size={18} />{error}</div>}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          hidden
          onChange={(event) => void handleFiles(event.target.files)}
        />

        {page === 'dashboard' && (
          <section>
            <p className="subtitle">Upload synthetic medical documents and transform them into structured, reviewable information.</p>
            <div className="stats-grid">
              <MetricCard label="Total documents" value={stats.total} helper="All uploaded files" icon={<FileText />} />
              <MetricCard label="Completed" value={stats.completed} helper="Successfully processed" icon={<CheckCircle2 />} />
              <MetricCard label="Failed" value={stats.failed} helper="Requires attention" icon={<AlertTriangle />} />
            </div>

            <div
              className={dragging ? 'upload-panel dragging' : 'upload-panel'}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); void handleFiles(event.dataTransfer.files); }}
            >
              <UploadCloud size={42} />
              <h2>{uploading ? 'Uploading document...' : 'Upload a medical document'}</h2>
              <p>Drag and drop a PDF, PNG, or JPG. Maximum file size: 10 MB.</p>
              <button className="primary-button" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
                {uploading ? 'Uploading...' : 'Browse files'}
              </button>
            </div>

            {loading
              ? <div className="panel processing-card"><div className="spinner" /><p>Loading documents...</p></div>
              : <DocumentTable title="Recent documents" documents={documents.slice(0, 4)} onOpen={openDocument} />}
          </section>
        )}

        {page === 'documents' && (
          <section>
            <div className="search-row">
              <div className="search-box"><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documents, types, or status" /></div>
              <button className="primary-button" disabled={uploading} onClick={() => fileInputRef.current?.click()}><UploadCloud size={17} />Upload</button>
            </div>
            <DocumentTable title="All documents" documents={filteredDocuments} onOpen={openDocument} />
          </section>
        )}

        {page === 'monitoring' && <Monitoring documents={documents} />}
        {page === 'details' && selectedDocument && <DocumentDetails document={selectedDocument} onBack={() => setPage('documents')} />}
      </main>
    </div>
  );
}

function MetricCard({ label, value, helper, icon }: { label: string; value: number; helper: string; icon: JSX.Element }) {
  return <article className="metric-card"><div className="metric-icon">{icon}</div><div><span>{label}</span><strong>{value}</strong><small>{helper}</small></div></article>;
}

function DocumentTable({ title, documents, onOpen }: { title: string; documents: ApiDocument[]; onOpen: (doc: ApiDocument) => void }) {
  return (
    <div className="panel table-panel">
      <div className="panel-heading"><h2>{title}</h2><span>{documents.length} items</span></div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>File</th><th>Type</th><th>Status</th><th>Uploaded</th><th>Processing</th><th /></tr></thead>
          <tbody>
            {documents.length === 0 && <tr><td colSpan={6}>No documents have been uploaded yet.</td></tr>}
            {documents.map((doc) => (
              <tr key={doc.id} onClick={() => onOpen(doc)}>
                <td><div className="file-cell"><FileText size={18} /><span>{doc.filename}</span></div></td>
                <td>{doc.document_type ?? 'Unclassified'}</td>
                <td><StatusBadge status={doc.status} /></td>
                <td>{formatUploaded(doc.created_at)}</td>
                <td>{formatProcessingTime(doc.processing_time_ms)}</td>
                <td><ChevronRight size={18} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DocumentDetails({ document, onBack }: { document: ApiDocument; onBack: () => void }) {
  const processing = document.status === 'UPLOADED' || document.status === 'PROCESSING';
  const structuredData = document.structured_data ?? {};
  const confidence = structuredData.confidence;

  return (
    <section>
      <button className="text-button" onClick={onBack}>← Back to documents</button>
      <div className="details-header">
        <div><p className="eyebrow">DOCUMENT</p><h2>{document.filename}</h2></div>
        <StatusBadge status={document.status} />
      </div>

      {processing ? (
        <div className="panel processing-card">
          <div className="spinner" />
          <h2>Processing document</h2>
          <p>The pipeline is extracting text, classifying the document, and generating structured output.</p>
          <div className="pipeline">
            {['Uploaded', 'OCR extraction', 'AI analysis', 'Validation', 'Complete'].map((step, index) => {
              const processingIndex = document.status === 'UPLOADED' ? 1 : 2;
              return <div key={step} className={index < processingIndex ? 'pipeline-step done' : index === processingIndex ? 'pipeline-step current' : 'pipeline-step'}><span>{index + 1}</span><small>{step}</small></div>;
            })}
          </div>
        </div>
      ) : document.status === 'FAILED' ? (
        <div className="panel processing-card">
          <XCircle size={40} />
          <h2>Processing failed</h2>
          <p>{document.error_message ?? 'The document could not be processed.'}</p>
        </div>
      ) : (
        <>
          <div className="details-grid">
            <div className="panel document-preview">
              <div className="paper">
                <strong>{document.document_type ?? 'Medical Document'}</strong>
                <p>Uploaded file: {document.filename}</p>
                <p>Uploaded: {formatUploaded(document.created_at)}</p>
                <hr />
                <p>{document.ocr_text ?? 'No OCR content is available.'}</p>
              </div>
            </div>
            <div className="panel summary-card">
              <p className="eyebrow">AI-GENERATED SUMMARY</p>
              <h2>{document.document_type ?? 'Document analysis'}</h2>
              <p>{document.ai_summary ?? 'No AI summary is available.'}</p>
              <div className="info-list">
                <Info label="Document type" value={document.document_type ?? 'Unknown'} />
                <Info label="Priority" value={String(structuredData.priority ?? 'Unknown')} />
                <Info label="Department" value={String(structuredData.department ?? 'Unknown')} />
                <Info label="Confidence" value={typeof confidence === 'number' ? `${Math.round(confidence * 100)}%` : 'Unknown'} />
              </div>
              <div className="notice"><AlertTriangle size={18} />AI-generated output. A healthcare professional must review it before use.</div>
            </div>
          </div>
          <div className="details-grid lower-grid">
            <div className="panel text-panel"><h3>Extracted OCR text</h3><p>{document.ocr_text ?? 'No OCR text available.'}</p></div>
            <div className="panel text-panel"><h3>Structured data</h3><pre>{JSON.stringify(structuredData, null, 2)}</pre></div>
          </div>
        </>
      )}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function Monitoring({ documents }: { documents: ApiDocument[] }) {
  const completed = documents.filter((document) => document.status === 'COMPLETED');
  const failed = documents.filter((document) => document.status === 'FAILED');
  const averageMilliseconds = completed.length
    ? completed.reduce((sum, item) => sum + (item.processing_time_ms ?? 0), 0) / completed.length
    : 0;
  const successRate = documents.length ? Math.round((completed.length / documents.length) * 100) : 0;

  return (
    <section>
      <p className="subtitle">Operational metrics calculated from the document-processing workflow.</p>
      <div className="stats-grid">
        <MetricCard label="Processed" value={completed.length} helper="Completed workflows" icon={<FileText />} />
        <MetricCard label="Success rate" value={successRate} helper="All documents (%)" icon={<CheckCircle2 />} />
        <MetricCard label="Active failures" value={failed.length} helper="Needs investigation" icon={<AlertTriangle />} />
      </div>
      <div className="monitor-grid">
        <div className="panel">
          <div className="panel-heading"><h2>Pipeline latency</h2><span>Current demo</span></div>
          {[
            ['Upload', 'Local', 15],
            ['OCR', 'Mock', 55],
            ['LLM', averageMilliseconds ? `${(averageMilliseconds / 1000).toFixed(1)} s total` : 'No data', 75],
            ['Validation', 'Pydantic', 22],
          ].map(([label, value, width]) => <div className="metric-row" key={String(label)}><div><span>{label}</span><strong>{value}</strong></div><div className="bar"><span style={{ width: `${width}%` }} /></div></div>)}
        </div>
        <div className="panel">
          <div className="panel-heading"><h2>Recent events</h2><span>Database</span></div>
          <div className="event-list">
            {documents.slice(0, 5).map((document) => (
              <Event
                key={document.id}
                type={document.status === 'FAILED' ? 'error' : 'success'}
                text={`${document.filename}: ${displayStatus(document.status)}`}
                time={formatUploaded(document.created_at)}
              />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Event({ type, text, time }: { type: 'success' | 'error'; text: string; time: string }) {
  return <div className="event"><span className={type}>{type === 'success' ? <CheckCircle2 size={17} /> : <XCircle size={17} />}</span><p>{text}</p><small>{time}</small></div>;
}

export default App;
