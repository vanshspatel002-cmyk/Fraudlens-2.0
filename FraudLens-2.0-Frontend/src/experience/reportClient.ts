const base = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

export type ReportVersion = {
  snapshot_id: string;
  run_id?: string;
  snapshot_created_at: number;
  pdf_status: 'pending' | 'ready' | 'failed';
  generated_at?: number;
  renderer_version?: string;
};

async function reportRequest<T>(path: string, options: RequestInit, consume: (response: Response) => Promise<T>, timeoutMs=45000): Promise<T> {
  const token = sessionStorage.getItem('fraudlens_admin_token');
  if (!token) throw new Error('Sign in to your reviewer account to access reports.');
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(base + path, {...options, signal: controller.signal, headers: {...options.headers, Authorization: 'Bearer ' + token}});
    if (token !== sessionStorage.getItem('fraudlens_admin_token')) throw new Error('Your reviewer session changed. Open the report again.');
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('fraudlens-session-expired'));
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || error.detail || 'The report could not be loaded. Retry when the service is available.');
    }
    const result = await consume(response);
    if (token !== sessionStorage.getItem('fraudlens_admin_token')) throw new Error('Your reviewer session changed. Open the report again.');
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('The report request timed out. Your saved analysis is intact; retry preview or download.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

const reportsPath = (id: string) => '/v1/cases/' + encodeURIComponent(id) + '/reports';
export async function reportVersions(id: string): Promise<ReportVersion[]> {
  return reportRequest(reportsPath(id), {}, async response => (await response.json()).reports as ReportVersion[]);
}
export async function prepareReport(id: string, snapshot?: string): Promise<ReportVersion> {
  const query = snapshot ? '?snapshot_id=' + encodeURIComponent(snapshot) : '';
  // Cold Unicode fonts, evidence freezing and cloud persistence exceeded 45s
  // in the real underwriting rehearsal. Keep generation bounded separately.
  return reportRequest(reportsPath(id) + '/prepare' + query, {method: 'POST'}, response => response.json() as Promise<ReportVersion>,180000);
}
export async function fetchReportPdf(id: string, snapshot: string, download = false) {
  return reportRequest(reportsPath(id) + '/' + encodeURIComponent(snapshot) + '/pdf' + (download ? '?download=true' : ''), {}, async response => {
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'FraudLens-' + id + '-' + snapshot.slice(0, 12) + '.pdf';
    return {blob: await response.blob(), filename};
  });
}
