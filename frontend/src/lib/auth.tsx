import {
  createContext,
  PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiRequest } from "./api";

type AuthRole = "student" | "counsellor" | "admin" | "system";

type AuthState = {
  accessToken: string;
  role: AuthRole;
  username: string;
  studentId: number | null;
  displayName: string | null;
  authProvider: string | null;
  passwordResetRequired: boolean;
};

type LoginPayload = {
  username: string;
  password: string;
};

type AuthContextValue = {
  auth: AuthState | null;
  isAuthenticated: boolean;
  login: (payload: LoginPayload) => Promise<AuthState>;
  resetPassword: (payload: { currentPassword: string; newPassword: string }) => Promise<void>;
  logout: () => void;
};

const STORAGE_KEY = "retentionos.auth";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [auth, setAuth] = useState<AuthState | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }
    try {
      setAuth(JSON.parse(raw) as AuthState);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      auth,
      isAuthenticated: Boolean(auth?.accessToken),
      async login(payload) {
        const response = await apiRequest<{
          access_token: string;
          username: string;
          role: AuthRole;
          student_id: number | null;
          display_name: string | null;
          auth_provider?: string | null;
          password_reset_required?: boolean;
        }>("/auth/login", {
          method: "POST",
          body: payload,
          timeoutMs: 15000,
        });

        const nextState: AuthState = {
          accessToken: response.access_token,
          username: response.username,
          role: response.role,
          studentId: response.student_id ?? null,
          displayName: response.display_name ?? null,
          authProvider: response.auth_provider ?? null,
          passwordResetRequired: Boolean(response.password_reset_required),
        };
        setAuth(nextState);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
        return nextState;
      },
      async resetPassword(payload) {
        if (!auth?.accessToken) {
          throw new Error("You must be signed in to reset your password.");
        }
        await apiRequest("/auth/reset-password", {
          method: "POST",
          token: auth.accessToken,
          body: {
            current_password: payload.currentPassword,
            new_password: payload.newPassword,
          },
        });
        const nextState: AuthState = {
          ...auth,
          passwordResetRequired: false,
        };
        setAuth(nextState);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
      },
      logout() {
        setAuth(null);
        localStorage.removeItem(STORAGE_KEY);
      },
    }),
    [auth],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}
