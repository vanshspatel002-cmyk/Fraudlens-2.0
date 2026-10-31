import { API_BASE } from './api-transport';

// Allow the configured local API without disabling the browser policy.
const configuredApiOrigin = (() => {
  try {
    const url = new URL(API_BASE);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    return url.protocol === 'https:' || (url.protocol === 'http:' && loopback) ? url.origin : '';
  } catch { return ''; }
})();

export function applySecurityHeaders(response: Response) {
  const h = new Headers(response.headers);
  h.set(
    "Content-Security-Policy",
    `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; media-src 'self' https:; connect-src 'self' https: ${configuredApiOrigin}; worker-src 'self' blob:; frame-src 'self' blob:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'`,
  );
  h.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  h.set("X-Content-Type-Options", "nosniff");
  h.set("Referrer-Policy", "strict-origin-when-cross-origin");
  h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: h,
  });
}
