const api = process.env.FOODFLOW_API_URL || "http://127.0.0.1:8000";
export default {
  output: process.env.FOODFLOW_STANDALONE === "1" ? "standalone" : undefined,
  // Allow a separate local PostgreSQL preview without replacing the SQLite build.
  distDir: process.env.FOODFLOW_NEXT_DIST_DIR || ".next",
  async rewrites() { return [{ source: "/api/:path*", destination: `${api}/:path*` }]; },
};
