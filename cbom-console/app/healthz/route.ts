export function GET() {
  return Response.json({ status: "ok", service: "cbom-workbench-console" }, { headers: { "Cache-Control": "no-store" } });
}
