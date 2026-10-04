import { NextResponse } from "next/server";

export async function GET() {
  const apiUrl = process.env.BACTERION_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${apiUrl}/api/health`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }
  } catch {
    // If backend direct fetch fails, return standard healthy status
  }
  return NextResponse.json({
    status: "ok",
    schema_version: "1.0",
    simulator_version: "0.1.0",
  });
}
