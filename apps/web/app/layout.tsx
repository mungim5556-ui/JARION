import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JARION 원격 실습실",
  description: "학교 실습실 PC 를 원격으로 켜고 브라우저로 접속합니다",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
