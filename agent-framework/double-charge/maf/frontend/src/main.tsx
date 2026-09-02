import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { CopilotKit } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CopilotKit runtimeUrl="/api/copilotkit" showDevConsole={false}>
      <App />
    </CopilotKit>
  </StrictMode>
);
