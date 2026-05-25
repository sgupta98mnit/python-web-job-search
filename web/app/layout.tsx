import type { Metadata } from "next";
import { JetBrains_Mono, Orbitron, Share_Tech_Mono } from "next/font/google";

import { GridBackground, ScanlineOverlay } from "@/components/cyber";
import "./globals.css";

const orbitron = Orbitron({
  subsets: ["latin"],
  variable: "--font-orbitron",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

const shareTech = Share_Tech_Mono({
  subsets: ["latin"],
  variable: "--font-share-tech",
  weight: "400",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Job Search Control Plane",
  description: "Application tracking and tailored resume generation.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${orbitron.variable} ${jetbrains.variable} ${shareTech.variable} dark`}
      suppressHydrationWarning
    >
      <body>
        <GridBackground />
        {children}
        <ScanlineOverlay />
      </body>
    </html>
  );
}
