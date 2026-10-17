import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { IncidentDetail } from "./pages/IncidentDetail";
import { Overview } from "./pages/Overview";

// The charts library is large: load the metrics page only when it is opened.
const ServiceMetrics = lazy(() =>
  import("./pages/ServiceMetrics").then((m) => ({ default: m.ServiceMetrics })),
);

const SERVICES = ["api-gateway", "payment-service", "database-service"];

export function App() {
  return (
    <>
      <div className="banner" role="note">
        Simulated data - no real infrastructure is monitored.
      </div>
      <header className="topbar">
        <NavLink to="/" className="brand">AI SRE Assistant</NavLink>
        <nav>
          <NavLink to="/" end>Overview</NavLink>
          {SERVICES.map((id) => (
            <NavLink key={id} to={`/services/${id}`}>{id}</NavLink>
          ))}
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/incidents/:id" element={<IncidentDetail />} />
          <Route
            path="/services/:id"
            element={
              <Suspense fallback={<p className="empty">Loading…</p>}>
                <ServiceMetrics />
              </Suspense>
            }
          />
          <Route path="*" element={<p className="empty">Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
