import { useEffect, useState, type ReactNode } from "react";

import { useLive } from "../live";
import { PauseIcon, PlayIcon } from "../icons";

/** Live / paused switch with "updated 3s ago", like dashboard tools. */
export function LiveIndicator({ updatedAt }: { updatedAt: number | null }) {
  const { paused, setPaused } = useLive();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const age = updatedAt ? Math.max(0, Math.round((now - updatedAt) / 1000)) : null;

  return (
    <button
      type="button"
      className={`live ${paused ? "paused" : ""}`}
      onClick={() => setPaused(!paused)}
      title={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
    >
      {paused ? <PlayIcon /> : <span className="live-dot" aria-hidden="true" />}
      {paused ? "Paused" : "Live"}
      {age !== null && <span className="muted">· {age}s ago</span>}
      {!paused && <PauseIcon />}
    </button>
  );
}

export function PageHeader({
  title,
  subtitle,
  updatedAt,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  updatedAt?: number | null;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="muted">{subtitle}</div>}
      </div>
      <div className="page-actions">
        {children}
        {updatedAt !== undefined && <LiveIndicator updatedAt={updatedAt} />}
      </div>
    </header>
  );
}
