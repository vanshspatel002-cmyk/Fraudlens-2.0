/** Public origin for canonical URLs and link previews. Set before a production build. */
const origin = (import.meta.env.VITE_PUBLIC_SITE_URL || "http://localhost:5173").replace(/\/$/, "");
export function siteUrl(path: string) {
  return new URL(path, origin + "/").href;
}
