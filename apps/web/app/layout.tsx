import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AppShell } from "@/components/ui/AppShell";

import "./globals.css";

/**
 * Both faces come from Google Fonts through next/font, which downloads them
 * at build time and serves them from our own origin. That removes the render
 * blocking request to fonts.googleapis.com, and it keeps the app working
 * inside hospital networks that block third party font CDNs outright.
 */
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  title: {
    default: "Pretrial.ai",
    template: "%s | Pretrial.ai",
  },
  description:
    "Clinical trial feasibility on statistically validated synthetic patient cohorts.",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
