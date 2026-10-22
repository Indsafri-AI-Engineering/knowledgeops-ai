import React from "react";
import { createRoot } from "react-dom/client";

function App() {
  return (
    <main>
      <h1>KnowledgeOps AI</h1>
      <p>The application workspace is ready for development.</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
