// M5-03 owner mode: Cognito sign-in (SRP, the password never leaves the browser in clear) and the owner-only
// approval write. Visitors never need this; they keep the browser sandbox. Tokens stay in memory only.
import { AuthenticationDetails, CognitoUser, CognitoUserPool, type CognitoUserSession } from "amazon-cognito-identity-js";

export interface OwnerConfig { region: string; pool_id: string; client_id: string }
export interface OwnerSession { username: string; accessToken: string; expiresAt: number }
export type SignInResult = { kind: "signed_in"; session: OwnerSession } | { kind: "new_password"; user: CognitoUser };

export async function loadOwnerConfig(): Promise<OwnerConfig | null> {
  const res = await fetch("/api/owner-config", { cache: "no-store" }).catch(() => null);
  if (!res || !res.ok) return null;
  const c = (await res.json()) as Partial<OwnerConfig>;
  return c.pool_id && c.client_id && c.region ? (c as OwnerConfig) : null;
}

/** Reads the `cognito:groups` claim of an access token (display only; the API re-checks it with Cognito). */
export function tokenGroups(token: string): string[] {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(part + "=".repeat((4 - (part.length % 4)) % 4)));
    return Array.isArray(claims["cognito:groups"]) ? claims["cognito:groups"] : [];
  } catch {
    return [];
  }
}

function toSession(user: CognitoUser, s: CognitoUserSession): OwnerSession {
  const at = s.getAccessToken();
  return { username: user.getUsername(), accessToken: at.getJwtToken(), expiresAt: at.getExpiration() * 1000 };
}

export function signIn(cfg: OwnerConfig, username: string, password: string): Promise<SignInResult> {
  const pool = new CognitoUserPool({ UserPoolId: cfg.pool_id, ClientId: cfg.client_id, Storage: memoryStorage() });
  const user = new CognitoUser({ Username: username, Pool: pool, Storage: memoryStorage() });
  return new Promise((resolve, reject) => {
    user.authenticateUser(new AuthenticationDetails({ Username: username, Password: password }), {
      onSuccess: (s) => resolve({ kind: "signed_in", session: toSession(user, s) }),
      onFailure: (e: Error) => reject(new Error(e?.message || "Sign-in failed")),
      newPasswordRequired: () => resolve({ kind: "new_password", user }),
      totpRequired: () => reject(new Error("Authenticator codes are not supported here yet")),
    });
  });
}

export function setNewPassword(user: CognitoUser, password: string): Promise<OwnerSession> {
  return new Promise((resolve, reject) => {
    user.completeNewPasswordChallenge(password, {}, {
      onSuccess: (s) => resolve(toSession(user, s)),
      onFailure: (e: Error) => reject(new Error(e?.message || "Could not set the password")),
    });
  });
}

/** Keeps the library's token cache in memory, so nothing persists after the tab closes. */
function memoryStorage() {
  const m = new Map<string, string>();
  return {
    setItem: (k: string, v: string) => void m.set(k, v),
    getItem: (k: string) => m.get(k) ?? null,
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
  };
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export interface DecisionInput { action_id: string; action_type: string; target: string; decision: "approved" | "rejected"; rationale: string }

export async function recordDecision(session: OwnerSession, d: DecisionInput): Promise<void> {
  if (Date.now() >= session.expiresAt) throw new Error("Your sign-in expired. Sign in again.");
  const body = JSON.stringify(d);
  const res = await fetch("/api/approvals", {
    method: "POST",
    headers: { "content-type": "application/json", "x-amz-content-sha256": await sha256Hex(body), "x-mc-owner-token": session.accessToken },
    body,
  });
  if (res.status !== 201) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Request failed (${res.status})`);
  }
}
