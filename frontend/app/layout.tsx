import type { Metadata } from "next";
import TopNav from "@/components/TopNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Data Governance AI | Portal",
  description: "NL2SQL query engine and FWA anomaly detection over the healthcare_insurance dataset.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        <TopNav />
        {children}
      </body>
    </html>
  );
}
