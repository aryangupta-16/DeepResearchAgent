import "@/app/globals.css";
import type { ReactNode } from "react";
import AppShell from "@/components/shell/AppShell";

export const metadata = {
  title: "Deep Research Agent",
  description:
    "Async, citation-grounded deep research — powered by the deep-research-agent backend.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}