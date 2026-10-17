import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { LiveProvider } from "./live";
import "@fontsource/b612/400.css";
import "@fontsource/b612/700.css";
import "./styles.css";
import { ToastProvider } from "./toast";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <LiveProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </LiveProvider>
    </BrowserRouter>
  </StrictMode>,
);
