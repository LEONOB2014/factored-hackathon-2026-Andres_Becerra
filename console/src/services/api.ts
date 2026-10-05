// Client for the BETA AID copilot API. Every real call goes through here; pages never call fetch.
// One deployment per residency region (ADR-021): the console talks only to the region the user selects.

export type RegionId = "mx" | "sa" | "demo";

export interface Region {
  id: RegionId;
  label: string;
  countries: string[];
  base: string;
}

const env = import.meta.env;

export const REGIONS: Region[] = [
  { id: "mx", label: "México · Querétaro", countries: ["MX"], base: env.VITE_API_MX ?? "https://beta-aid-mx-621442591789.northamerica-south1.run.app" },
  { id: "sa", label: "Colombia y Argentina · São Paulo", countries: ["CO", "AR"], base: env.VITE_API_SA ?? "https://beta-aid-sa-621442591789.southamerica-east1.run.app" },
  { id: "demo", label: "Demo rápida (todas)", countries: ["MX", "CO", "AR"], base: env.VITE_API_DEMO ?? "https://aleonardobecerra--beta-aid-copilot-web.modal.run" },
];

export const regionById = (id: RegionId): Region => REGIONS.find((r) => r.id === id) ?? REGIONS[2];

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status} ${detail}`);
  }
}

export async function api<T>(
  region: RegionId,
  path: string,
  opts: { method?: "GET" | "POST"; body?: unknown; token?: string | null; staffCode?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.token) headers.authorization = `Bearer ${opts.token}`;
  if (opts.staffCode) headers["x-staff-code"] = opts.staffCode;
  const res = await fetch(regionById(region).base + path, {
    method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, String(detail));
  }
  return (await res.json()) as T;
}
