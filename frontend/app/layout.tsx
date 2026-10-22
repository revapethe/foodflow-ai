import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "FoodFlow | Supply Chain Intelligence", description: "Delivery analytics grounded in warehouse results" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
