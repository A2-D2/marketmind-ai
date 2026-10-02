import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MarketMind — Agentic Equity Research",
  description: "Multi-agent, evidence-cited equity research.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
