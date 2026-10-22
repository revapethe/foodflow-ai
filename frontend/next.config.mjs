const api = process.env.FOODFLOW_API_URL || "http://127.0.0.1:8000";
export default {
  async rewrites() { return [{ source: "/api/:path*", destination: `${api}/:path*` }]; },
};
