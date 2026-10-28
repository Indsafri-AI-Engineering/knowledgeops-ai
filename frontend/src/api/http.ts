import { getOidcAccessToken, isOidcMode } from "./oidc";

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (isOidcMode()) {
    const accessToken = await getOidcAccessToken();
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return fetch(input, {
    ...init,
    headers,
    credentials: isOidcMode() ? "omit" : "include",
  });
}
