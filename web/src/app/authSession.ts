export type AuthUser = {
  id: number;
  user_name: string | null;
};

const authUserStorageKey = "claude-sdk.auth.user";

function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<AuthUser>;
  return (
    typeof candidate.id === "number" &&
    Number.isFinite(candidate.id) &&
    (typeof candidate.user_name === "string" || candidate.user_name === null)
  );
}

export function readStoredAuthUser(storage: Storage): AuthUser | null {
  try {
    const raw = storage.getItem(authUserStorageKey);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as unknown;
    return isAuthUser(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveStoredAuthUser(storage: Storage, user: AuthUser) {
  try {
    storage.setItem(authUserStorageKey, JSON.stringify(user));
  } catch {
    // localStorage 在隐私模式或配额异常时可能失败；登录主流程不因此中断。
  }
}

export function clearStoredAuthUser(storage: Storage) {
  try {
    storage.removeItem(authUserStorageKey);
  } catch {
    // localStorage 不可写时忽略，页面内状态会继续清理。
  }
}

export function readBrowserAuthUser(): AuthUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  return readStoredAuthUser(window.localStorage);
}

export function saveBrowserAuthUser(user: AuthUser) {
  if (typeof window === "undefined") {
    return;
  }
  saveStoredAuthUser(window.localStorage, user);
}

export function clearBrowserAuthUser() {
  if (typeof window === "undefined") {
    return;
  }
  clearStoredAuthUser(window.localStorage);
}
