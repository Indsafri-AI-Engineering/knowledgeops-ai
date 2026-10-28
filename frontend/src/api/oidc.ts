import {
  UserManager,
  WebStorageStateStore,
  type User,
} from "oidc-client-ts";

const oidcMode = (import.meta.env.VITE_AUTH_MODE ?? "oidc").toLowerCase() === "oidc";
let manager: UserManager | null = null;
let callbackPromise: Promise<void> | null = null;

export function isOidcMode(): boolean {
  return oidcMode;
}

export function getOidcAuthority(): string | null {
  return import.meta.env.VITE_OIDC_AUTHORITY || null;
}

function userManager(): UserManager {
  if (!oidcMode) {
    throw new Error("OIDC authentication is not enabled in this frontend.");
  }
  if (!manager) {
    const authority = getOidcAuthority();
    const clientId = import.meta.env.VITE_OIDC_CLIENT_ID;
    if (!authority || !clientId) {
      throw new Error("Set VITE_OIDC_AUTHORITY and VITE_OIDC_CLIENT_ID.");
    }
    manager = new UserManager({
      authority,
      client_id: clientId,
      redirect_uri: `${window.location.origin}/`,
      post_logout_redirect_uri: `${window.location.origin}/`,
      response_type: "code",
      scope: "openid profile email",
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    });
  }
  return manager;
}

export function completeOidcCallback(): Promise<void> {
  if (!oidcMode) return Promise.resolve();
  if (callbackPromise) return callbackPromise;

  const url = new URL(window.location.href);
  const providerError = url.searchParams.get("error");
  const hasCallback = providerError
    || (url.searchParams.has("code") && url.searchParams.has("state"));
  if (!hasCallback) return Promise.resolve();

  callbackPromise = Promise.resolve().then(async () => {
    try {
      if (providerError) {
        const description = url.searchParams.get("error_description");
        throw new Error(description ? `${providerError}: ${description}` : providerError);
      }
      await userManager().signinRedirectCallback();
    } finally {
      window.history.replaceState({}, document.title, url.pathname);
    }
  });
  return callbackPromise;
}

export async function getOidcUser(): Promise<User | null> {
  if (!oidcMode) return null;
  const oidcUser = await userManager().getUser();
  if (!oidcUser || oidcUser.expired) return null;
  return oidcUser;
}

export async function startOidcLogin(): Promise<void> {
  await userManager().signinRedirect();
}

export async function startOidcLogout(): Promise<void> {
  const currentUser = await userManager().getUser();
  await userManager().removeUser();
  if (currentUser?.id_token) {
    await userManager().signoutRedirect({ id_token_hint: currentUser.id_token });
  }
}

export async function getOidcAccessToken(): Promise<string | null> {
  const currentUser = await getOidcUser();
  return currentUser?.access_token ?? null;
}
