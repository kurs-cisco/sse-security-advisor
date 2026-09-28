"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

export function StatusBanner({ title, detail, onRetry }: { title: string; detail: string; onRetry?: () => void }) {
  return <div className="status-banner" role="alert" tabIndex={-1}>
    <AlertTriangle aria-hidden="true" size={19} />
    <div><strong>{title}</strong><p>{detail}</p></div>
    {onRetry ? <button type="button" onClick={onRetry}><RefreshCw size={15} />Retry</button> : null}
  </div>;
}
