import { ClerkProvider } from "@clerk/clerk-react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

function Root() {
  if (!publishableKey) {
    return (
      <main className="page centered">
        <p>
          Missing <code>VITE_CLERK_PUBLISHABLE_KEY</code>. Copy <code>.env.example</code> to{" "}
          <code>.env.local</code> and add your Clerk publishable key.
        </p>
      </main>
    );
  }
  return (
    <ClerkProvider publishableKey={publishableKey} afterSignOutUrl="/sign-in">
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ClerkProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
