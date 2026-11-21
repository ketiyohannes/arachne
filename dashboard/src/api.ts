/**
 * Access to the dashboard API. Served by `arachne dashboard` it needs no key; the hosted copy
 * sits behind a proxy that asks for one, given once as `#key=...` in the link and kept in this browser.
 */

const STORAGE = "arachne-key";

function readStored(): string {
  try {
    return localStorage.getItem(STORAGE) ?? "";
  } catch {
    return "";
  }
}

let key = readStored();

export function saveKey(next: string): void {
  key = next.trim();
  try {
    localStorage.setItem(STORAGE, key);
  } catch {
    // Private windows may refuse storage; the key then lasts until the page is closed.
  }
}

/** Take the key out of a `#key=...` link so it is not left in the address bar or shared by accident. */
export function adoptKeyFromLink(): void {
  const match = location.hash.match(/^#key=(.+)$/);
  if (!match) return;
  saveKey(decodeURIComponent(match[1]));
  history.replaceState(null, "", location.pathname + location.search);
}

export class ApiError extends Error {
  constructor(public status: number) {
    super(`request failed (${status})`);
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store", headers: key ? { "x-arachne-key": key } : {} });
  if (!response.ok) throw new ApiError(response.status);
  return response.json();
}
