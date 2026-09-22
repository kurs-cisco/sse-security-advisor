"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  DatabaseZap,
  FileArchive,
  FolderOpen,
  RefreshCw,
  TerminalSquare,
  UploadCloud,
} from "lucide-react";
import { fetchJson } from "@/app/lib/http";
import { Badge } from "@/app/components/ui/badge";
import { Card } from "@/app/components/ui/card";

type BatchState =
  | "uploading"
  | "submitting"
  | "queued"
  | "validating"
  | "running"
  | "succeeded"
  | "failed"
  | "expired";

type UploadTarget = {
  path: string;
  method: "PUT";
  url: string;
  headers: Record<string, string>;
};

type Comparison = {
  current_file_count: number;
  manifest_file_count: number;
  unchanged: number;
  changed: number;
  new: number;
  unobserved_current: number;
  changed_samples: string[];
  new_samples: string[];
  unobserved_current_samples: string[];
};

type BatchResult = {
  dry_run?: boolean;
  catalog_changes_applied?: boolean;
  checksum_verified_files?: number;
  inventory?: {
    total_files: number;
    total_bytes: number;
    document_kinds: Record<string, number>;
    issue_count: number;
  };
  comparison?: Comparison;
  ingest?: Record<string, unknown>;
};

type IngestionBatch = {
  id: string;
  source_collection: string;
  manifest_sha256: string;
  dry_run: boolean;
  authoritative_snapshot: boolean;
  state: BatchState;
  expected_file_count: number;
  expected_total_bytes: number;
  verified_file_count: number;
  upload_expires_at: string;
  ecs_task_arn: string | null;
  ingest_run_id: number | null;
  result: BatchResult | null;
  error_summary: string | null;
  created_by_email: string | null;
  created_by_token_prefix: string | null;
  created_at: string;
  submitted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  uploads?: UploadTarget[];
};

type LogEvent = { timestamp: number | null; ingestion_time: number | null; message: string };
type BatchLogs = {
  available: boolean;
  log_group: string | null;
  log_stream: string | null;
  items: LogEvent[];
};

type SelectedFile = { file: File; path: string };
type ManifestFile = {
  path: string;
  sha256: string;
  size_bytes: number;
  content_type: string;
  modified_at: null;
};

type PipelineProgress = {
  phase: "idle" | "hashing" | "creating" | "uploading" | "submitting";
  completed: number;
  total: number;
  message: string;
};

const ACTIVE_STATES = new Set<BatchState>(["submitting", "queued", "validating", "running"]);
const EXCLUDED_DIRECTORIES = new Set([".git", ".venv", "__pycache__", "cbom-catalog", "graphify-out"]);

function statusTone(state: BatchState): "neutral" | "info" | "warning" | "danger" | "success" {
  if (state === "succeeded") return "success";
  if (state === "failed" || state === "expired") return "danger";
  if (state === "uploading") return "warning";
  return "info";
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / (1024 ** unit);
  return `${amount.toFixed(unit === 0 || amount >= 10 ? 0 : 1)} ${units[unit]}`;
}

function formatTime(value: string | number | null): string {
  if (value === null) return "Not started";
  const parsed = typeof value === "number" ? new Date(value) : new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unknown" : parsed.toLocaleString();
}

function contentType(path: string): string {
  return path.toLocaleLowerCase().endsWith(".csv") ? "text/csv" : "application/json";
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

async function sha256(value: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", value);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function normalizedSelection(fileList: FileList): SelectedFile[] {
  const supported = Array.from(fileList).filter((file) => /\.(json|csv)$/i.test(file.name));
  const splitPaths = supported.map((file) => (file.webkitRelativePath || file.name).split("/"));
  const commonRoot = splitPaths.length > 0
    && splitPaths.every((parts) => parts.length > 1 && parts[0] === splitPaths[0][0]);
  const seen = new Set<string>();
  const selection: SelectedFile[] = [];

  supported.forEach((file, index) => {
    const parts = commonRoot ? splitPaths[index].slice(1) : splitPaths[index];
    const path = parts.join("/");
    const directories = parts.slice(0, -1);
    if (directories.some((part) => part.startsWith(".") || EXCLUDED_DIRECTORIES.has(part))) return;
    if (seen.has(path)) throw new Error(`The selected folder contains a duplicate path: ${path}`);
    seen.add(path);
    selection.push({ file, path });
  });
  return selection.sort((left, right) => {
    const folded = left.path.toLocaleLowerCase().localeCompare(right.path.toLocaleLowerCase());
    return folded || left.path.localeCompare(right.path);
  });
}

function ResultPanel({ batch }: { batch: IngestionBatch }) {
  const result = batch.result;
  if (!result) {
    return <div className="ingestion-empty"><Clock3 size={20} /><p>Results appear after validation completes.</p></div>;
  }
  const comparison = result.comparison;
  return <div className="ingestion-results">
    <div className="ingestion-result-banner">
      <CheckCircle2 size={18} />
      <div><strong>{result.catalog_changes_applied ? "Catalog updated" : "Dry run completed without catalog changes"}</strong><span>{result.checksum_verified_files ?? batch.verified_file_count} checksums verified</span></div>
    </div>
    {result.inventory && <div className="result-metrics">
      <div><span>Files</span><strong>{result.inventory.total_files.toLocaleString()}</strong></div>
      <div><span>Corpus size</span><strong>{formatBytes(result.inventory.total_bytes)}</strong></div>
      <div><span>Parse issues</span><strong>{result.inventory.issue_count.toLocaleString()}</strong></div>
    </div>}
    {comparison && <>
      <div className="comparison-grid">
        <div className="comparison-unchanged"><span>Unchanged</span><strong>{comparison.unchanged}</strong></div>
        <div className="comparison-changed"><span>Changed</span><strong>{comparison.changed}</strong></div>
        <div className="comparison-new"><span>New</span><strong>{comparison.new}</strong></div>
        <div className="comparison-unobserved"><span>Unobserved</span><strong>{comparison.unobserved_current}</strong></div>
      </div>
      {(comparison.changed_samples.length > 0 || comparison.new_samples.length > 0 || comparison.unobserved_current_samples.length > 0) && <details className="result-details">
        <summary>Review sample paths</summary>
        {comparison.changed_samples.length > 0 && <div><strong>Changed</strong><code>{comparison.changed_samples.join("\n")}</code></div>}
        {comparison.new_samples.length > 0 && <div><strong>New</strong><code>{comparison.new_samples.join("\n")}</code></div>}
        {comparison.unobserved_current_samples.length > 0 && <div><strong>Unobserved current</strong><code>{comparison.unobserved_current_samples.join("\n")}</code></div>}
      </details>}
    </>}
    {result.inventory?.document_kinds && <details className="result-details"><summary>Document inventory</summary><code>{Object.entries(result.inventory.document_kinds).map(([kind, count]) => `${kind}: ${count}`).join("\n")}</code></details>}
    {result.ingest && <details className="result-details"><summary>Ingest output</summary><code>{JSON.stringify(result.ingest, null, 2)}</code></details>}
  </div>;
}

export function IngestionWorkspace({ operatorReady }: { operatorReady: boolean }) {
  const directoryInput = useRef<HTMLInputElement>(null);
  const [batches, setBatches] = useState<IngestionBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<IngestionBatch | null>(null);
  const [logs, setLogs] = useState<BatchLogs | null>(null);
  const [files, setFiles] = useState<SelectedFile[]>([]);
  const [sourceCollection, setSourceCollection] = useState("sse-cboms");
  const [dryRun, setDryRun] = useState(true);
  const [authoritativeSnapshot, setAuthoritativeSnapshot] = useState(false);
  const [error, setError] = useState("");
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [progress, setProgress] = useState<PipelineProgress>({ phase: "idle", completed: 0, total: 0, message: "" });

  const busy = progress.phase !== "idle";
  const totalSelectedBytes = files.reduce((total, item) => total + item.file.size, 0);

  const loadJobs = useCallback(async () => {
    try {
      const page = await fetchJson<{ items: IngestionBatch[] }>("/api/v1/admin/ingestion/batches?limit=50", { dedupe: false });
      setBatches(page.items);
      setSelectedBatchId((current) => current ?? page.items[0]?.id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ingestion jobs are unavailable");
    } finally {
      setLoadingJobs(false);
    }
  }, []);

  const loadBatch = useCallback(async (batchId: string) => {
    setLoadingDetail(true);
    try {
      const batch = await fetchJson<IngestionBatch>(`/api/v1/admin/ingestion/batches/${batchId}`, { dedupe: false });
      setSelectedBatch(batch);
      try {
        setLogs(await fetchJson<BatchLogs>(`/api/v1/admin/ingestion/batches/${batchId}/logs?limit=300`, { dedupe: false }));
      } catch {
        setLogs({ available: false, log_group: null, log_stream: null, items: [] });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ingestion job details are unavailable");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    directoryInput.current?.setAttribute("webkitdirectory", "");
    const timer = window.setTimeout(() => void loadJobs(), 0);
    return () => window.clearTimeout(timer);
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedBatchId) return;
    const timer = window.setTimeout(() => void loadBatch(selectedBatchId), 0);
    return () => window.clearTimeout(timer);
  }, [loadBatch, selectedBatchId]);

  useEffect(() => {
    if (!batches.some((batch) => ACTIVE_STATES.has(batch.state))) return;
    const interval = window.setInterval(() => {
      void loadJobs();
      if (selectedBatchId) void loadBatch(selectedBatchId);
    }, 4_000);
    return () => window.clearInterval(interval);
  }, [batches, loadBatch, loadJobs, selectedBatchId]);

  function chooseFiles(fileList: FileList | null) {
    setError("");
    if (!fileList) return;
    try {
      const next = normalizedSelection(fileList);
      if (!next.length) throw new Error("No supported .json or .csv files were found in that folder");
      setFiles(next);
    } catch (caught) {
      setFiles([]);
      setError(caught instanceof Error ? caught.message : "The selected folder could not be read");
    }
  }

  async function startIngestion() {
    setError("");
    if (!files.length) {
      setError("Choose a folder containing .json or .csv corpus files first");
      return;
    }
    if (!/^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(sourceCollection)) {
      setError("Source collection must be a lowercase slug using letters, numbers, and hyphens");
      return;
    }
    if (!dryRun && !window.confirm("This run will update catalog data after validation. Continue?")) return;

    try {
      const manifestFiles: ManifestFile[] = [];
      setProgress({ phase: "hashing", completed: 0, total: files.length, message: "Computing local SHA-256 checksums" });
      for (let index = 0; index < files.length; index += 1) {
        const selected = files[index];
        manifestFiles.push({
          path: selected.path,
          sha256: await sha256(await selected.file.arrayBuffer()),
          size_bytes: selected.file.size,
          content_type: contentType(selected.path),
          modified_at: null,
        });
        setProgress({ phase: "hashing", completed: index + 1, total: files.length, message: `Hashed ${index + 1} of ${files.length} files` });
      }

      const normalizedManifest = {
        schema_version: 1,
        source_collection: sourceCollection,
        dry_run: dryRun,
        authoritative_snapshot: dryRun ? false : authoritativeSnapshot,
        files: manifestFiles,
      };
      const manifestSha256 = await sha256(new TextEncoder().encode(canonicalJson(normalizedManifest)).buffer);
      setProgress({ phase: "creating", completed: 0, total: files.length, message: "Creating checksum-gated upload batch" });
      const batch = await fetchJson<IngestionBatch>("/api/v1/admin/ingestion/batches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        timeoutMs: 60_000,
        body: JSON.stringify({
          source_collection: sourceCollection,
          dry_run: dryRun,
          authoritative_snapshot: dryRun ? false : authoritativeSnapshot,
          manifest_sha256: manifestSha256,
          files: manifestFiles.map(({ path, sha256: checksum, size_bytes, modified_at }) => ({ path, sha256: checksum, size_bytes, modified_at })),
        }),
      });
      if (!batch.uploads || batch.uploads.length !== files.length) throw new Error("The API returned an incomplete upload plan");

      setSelectedBatchId(batch.id);
      const sourceFiles = new Map(files.map((item) => [item.path, item.file]));
      let nextUpload = 0;
      let uploaded = 0;
      setProgress({ phase: "uploading", completed: 0, total: batch.uploads.length, message: "Uploading directly to private S3 storage" });
      const uploadWorker = async () => {
        while (nextUpload < (batch.uploads?.length ?? 0)) {
          const index = nextUpload;
          nextUpload += 1;
          const target = batch.uploads?.[index];
          if (!target) return;
          const file = sourceFiles.get(target.path);
          if (!file) throw new Error(`The upload plan referenced an unknown file: ${target.path}`);
          const headers = Object.fromEntries(Object.entries(target.headers).filter(([name]) => name.toLocaleLowerCase() !== "content-length"));
          const response = await fetch(target.url, { method: target.method, headers, body: file });
          if (!response.ok) throw new Error(`S3 rejected ${target.path} (${response.status})`);
          uploaded += 1;
          setProgress({ phase: "uploading", completed: uploaded, total: batch.uploads?.length ?? files.length, message: `Uploaded ${uploaded} of ${batch.uploads?.length ?? files.length} files` });
        }
      };
      await Promise.all(Array.from({ length: Math.min(6, batch.uploads.length) }, () => uploadWorker()));

      setProgress({ phase: "submitting", completed: files.length, total: files.length, message: "Launching the asynchronous validation task" });
      await fetchJson(`/api/v1/admin/ingestion/batches/${batch.id}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        timeoutMs: 60_000,
        body: JSON.stringify({ manifest_sha256: manifestSha256 }),
      });
      await loadJobs();
      await loadBatch(batch.id);
      setFiles([]);
      if (directoryInput.current) directoryInput.current.value = "";
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The ingestion batch could not be started");
      await loadJobs();
    } finally {
      setProgress({ phase: "idle", completed: 0, total: 0, message: "" });
    }
  }

  const pipelinePercent = progress.total ? Math.round((progress.completed / progress.total) * 100) : 0;
  const validationPercent = selectedBatch?.expected_file_count
    ? Math.round((selectedBatch.verified_file_count / selectedBatch.expected_file_count) * 100)
    : 0;

  return <section className="ingestion-workspace" aria-labelledby="ingestion-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Checksum-gated corpus intake</p><h2 id="ingestion-heading"><DatabaseZap size={20} />Data ingestion</h2><p>Upload CBOMs and evidence directly to private S3, then validate and ingest them asynchronously.</p></div>
      <button className="secondary-button" onClick={() => void loadJobs()} disabled={loadingJobs}><RefreshCw size={15} className={loadingJobs ? "spin" : ""} />Refresh jobs</button>
    </div>
    {error && <div className="admin-error" role="alert"><AlertTriangle size={16} />{error}</div>}
    <div className="ingestion-layout">
      <Card className="ingestion-launch-card">
        <div className="card-heading"><div><p className="eyebrow">New batch</p><h3><UploadCloud size={18} />Select a corpus folder</h3></div><Badge tone={dryRun ? "info" : "warning"}>{dryRun ? "Dry run" : "Writes enabled"}</Badge></div>
        <div className="ingestion-form">
          <label>Source collection<input value={sourceCollection} onChange={(event) => setSourceCollection(event.target.value.toLocaleLowerCase())} disabled={busy} /></label>
          <label className="folder-picker"><FolderOpen size={18} /><span><strong>{files.length ? `${files.length.toLocaleString()} supported files selected` : "Choose folder"}</strong><small>{files.length ? `${formatBytes(totalSelectedBytes)} · .json and .csv only` : "The raw files upload directly from your browser to S3"}</small></span><input ref={directoryInput} type="file" multiple accept=".json,.csv,application/json,text/csv" onChange={(event) => chooseFiles(event.target.files)} disabled={busy} /></label>
          <div className="ingestion-options">
            <label className="check-option"><input type="checkbox" checked={dryRun} onChange={(event) => { setDryRun(event.target.checked); if (event.target.checked) setAuthoritativeSnapshot(false); }} disabled={busy} /><span><strong>Dry run</strong><small>Validate and compare without changing catalog data.</small></span></label>
            <label className="check-option"><input type="checkbox" checked={authoritativeSnapshot} onChange={(event) => setAuthoritativeSnapshot(event.target.checked)} disabled={busy || dryRun} /><span><strong>Authoritative snapshot</strong><small>Mark absent paths historical. Use only for a complete collection.</small></span></label>
          </div>
          {busy && <div className="pipeline-progress" aria-live="polite"><div><span>{progress.message}</span><strong>{pipelinePercent}%</strong></div><div className="progress-track"><div className="progress-fill" style={{ width: `${pipelinePercent}%` }} /></div></div>}
          {!operatorReady && <p className="ingestion-operator-note"><AlertTriangle size={14} />A provisioned OIDC administrator is required to start cloud ingestion. Local development can inspect job history and results.</p>}
          <button className="primary-button ingestion-start" onClick={() => void startIngestion()} disabled={busy || !files.length || !operatorReady}><UploadCloud size={16} />{dryRun ? "Upload and start dry run" : "Upload and ingest"}</button>
          <p className="ingestion-safety"><FileArchive size={14} />Raw corpus files are temporary S3 objects. They do not pass through FastAPI and are not stored in Git.</p>
        </div>
      </Card>

      <Card className="ingestion-jobs-card">
        <div className="card-heading"><div><p className="eyebrow">History</p><h3>Ingestion jobs</h3></div><Badge tone="neutral">{batches.length}</Badge></div>
        <div className="job-list">
          {loadingJobs && !batches.length && <div className="ingestion-empty"><Clock3 size={20} /><p>Loading jobs…</p></div>}
          {!loadingJobs && !batches.length && <div className="ingestion-empty"><FileArchive size={20} /><p>No ingestion jobs yet.</p></div>}
          {batches.map((batch) => <button key={batch.id} className={`job-list-item${selectedBatchId === batch.id ? " job-list-item-active" : ""}`} onClick={() => setSelectedBatchId(batch.id)}>
            <span className="job-state"><Badge tone={statusTone(batch.state)}>{batch.state}</Badge><small>{formatTime(batch.created_at)}</small></span>
            <span className="job-copy"><strong>{batch.source_collection}</strong><small>{batch.expected_file_count.toLocaleString()} files · {formatBytes(batch.expected_total_bytes)} · {batch.dry_run ? "dry run" : "catalog update"}</small></span>
            <ChevronRight size={17} />
          </button>)}
        </div>
      </Card>
    </div>

    {selectedBatch && <Card className="ingestion-detail-card">
      <div className="card-heading ingestion-detail-heading"><div><p className="eyebrow">Selected job</p><h3>{selectedBatch.source_collection}</h3><code>{selectedBatch.id}</code></div><div className="heading-actions"><Badge tone={selectedBatch.dry_run ? "info" : "warning"}>{selectedBatch.dry_run ? "Dry run" : "Catalog update"}</Badge><Badge tone={statusTone(selectedBatch.state)}>{selectedBatch.state}</Badge><button className="icon-button" aria-label="Refresh selected job" onClick={() => void loadBatch(selectedBatch.id)} disabled={loadingDetail}><RefreshCw size={15} className={loadingDetail ? "spin" : ""} /></button></div></div>
      <div className="job-summary-grid">
        <div><span>Validation</span><strong>{selectedBatch.verified_file_count.toLocaleString()} / {selectedBatch.expected_file_count.toLocaleString()}</strong><div className="progress-track"><div className="progress-fill" style={{ width: `${validationPercent}%` }} /></div></div>
        <div><span>Created</span><strong>{formatTime(selectedBatch.created_at)}</strong><small>{selectedBatch.created_by_email ?? (selectedBatch.created_by_token_prefix ? `${selectedBatch.created_by_token_prefix}…` : "Administrator")}</small></div>
        <div><span>Completed</span><strong>{formatTime(selectedBatch.completed_at)}</strong><small>{selectedBatch.ingest_run_id ? `Ingest run ${selectedBatch.ingest_run_id}` : selectedBatch.dry_run ? "Non-mutating validation" : "Awaiting ingest run"}</small></div>
        <div><span>Manifest</span><strong>{selectedBatch.manifest_sha256.slice(0, 12)}…</strong><small>{selectedBatch.authoritative_snapshot ? "Authoritative snapshot" : "Incremental scope"}</small></div>
      </div>
      {selectedBatch.error_summary && <div className="job-error"><AlertTriangle size={17} /><div><strong>Job failed</strong><span>{selectedBatch.error_summary}</span></div></div>}
      <div className="job-output-grid">
        <section><div className="output-heading"><h4><CheckCircle2 size={17} />Results</h4></div><ResultPanel batch={selectedBatch} /></section>
        <section><div className="output-heading"><h4><TerminalSquare size={17} />Task logs</h4><button className="text-link" onClick={() => void loadBatch(selectedBatch.id)}>Refresh</button></div>
          <div className="job-logs" role="log" aria-live="polite">
            {logs?.items.length ? logs.items.map((event, index) => <div key={`${event.timestamp ?? 0}-${index}`}><time>{event.timestamp ? formatTime(event.timestamp) : ""}</time><span>{event.message}</span></div>) : <div className="log-empty">{selectedBatch.ecs_task_arn ? "Waiting for task output…" : "Logs become available after the ECS task starts."}</div>}
          </div>
          {logs?.log_stream && <code className="log-stream">{logs.log_stream}</code>}
        </section>
      </div>
    </Card>}
  </section>;
}
