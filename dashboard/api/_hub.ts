/**
 * Proxy from the hosted dashboard to the hub: a machine on the tailnet running `arachne dashboard`.
 *
 *   HUB_URL        base URL of the hub, e.g. the HTTPS address of its published port
 *   HUB_TOKEN      optional bearer token the hub's address requires
 *   DASHBOARD_KEY  key a viewer must present; without it the deployment refuses every request
 *
 * The hub address and its token never reach the browser.
 */

declare const process: { env: Record<string, string | undefined> };

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

/** Compare digests rather than the strings, so timing does not reveal how much of a guess was right. */
async function sameSecret(given: string, expected: string): Promise<boolean> {
  const digest = async (text: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
  const [a, b] = await Promise.all([digest(given), digest(expected)]);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

export async function forward(request: Request, path: string): Promise<Response> {
  const { HUB_URL: hub, HUB_TOKEN: token, DASHBOARD_KEY: key } = process.env;
  if (!hub || !key) return json({ error: "HUB_URL and DASHBOARD_KEY must be set on this deployment" }, 500);
  if (!(await sameSecret(request.headers.get("x-arachne-key") ?? "", key))) return json({ error: "access key required" }, 401);

  const target = hub.replace(/\/+$/, "") + path + new URL(request.url).search;
  try {
    const response = await fetch(target, {
      headers: token ? { authorization: `Bearer ${token}` } : {},
      signal: AbortSignal.timeout(50_000), // a sleeping hub is woken by the request and may take a while
    });
    if (!response.ok) return json({ error: `hub answered ${response.status}` }, response.status === 409 ? 503 : response.status === 401 ? 502 : response.status);
    return new Response(response.body, {
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch {
    return json({ error: "hub did not answer" }, 503);
  }
}
