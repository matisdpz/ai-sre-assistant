import { lazy, Suspense, type ReactNode } from "react";
import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Incidents } from "./pages/Incidents";
import { Overview } from "./pages/Overview";

// The charts library is large: pages with full charts load it only when opened.
const IncidentDetail = lazy(() =>
  import("./pages/IncidentDetail").then((m) => ({ default: m.IncidentDetail })),
);
const ServiceMetrics = lazy(() =>
  import("./pages/ServiceMetrics").then((m) => ({ default: m.ServiceMetrics })),
);

const withSuspense = (page: ReactNode) => (
  <Suspense fallback={<p className="empty">Loading…</p>}>{page}</Suspense>
);

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:id" element={withSuspense(<IncidentDetail />)} />
        <Route path="/services/:id" element={withSuspense(<ServiceMetrics />)} />
        <Route path="*" element={<p className="empty">Page not found.</p>} />
      </Routes>
    </Layout>
  );
}
