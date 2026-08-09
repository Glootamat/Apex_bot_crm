import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { App } from "./app/App";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { queryClient } from "./lib/query";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element is missing");
createRoot(root).render(<StrictMode><ErrorBoundary><QueryClientProvider client={queryClient}><App /></QueryClientProvider></ErrorBoundary></StrictMode>);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  let refreshing = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!refreshing) { refreshing = true; window.location.reload(); }
  });
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").then((registration) => registration.update());
  });
}
