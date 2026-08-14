import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
  weight: ["300", "400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Datify — AI Data Scientist Copilot",
  description:
    "Autonomous, privacy-first data analysis powered by Claude. Drop a CSV, ask a question, get a chart.",
  keywords: ["data analysis", "AI", "ECharts", "CSV", "visualization"],
  authors: [{ name: "Datify" }],
  openGraph: {
    title: "Datify — AI Data Scientist Copilot",
    description: "Drop a CSV. Ask a question. Get a chart.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-[#0a0f28] text-[#f0f4ff]">
        {children}
      </body>
    </html>
  );
}
