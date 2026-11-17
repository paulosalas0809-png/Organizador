import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { FinanceProvider } from "./context/FinanceContext.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <FinanceProvider>
      <App />
    </FinanceProvider>
  </React.StrictMode>
);
