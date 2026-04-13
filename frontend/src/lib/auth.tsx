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
  studentId: number | null;
  displayName: string | null;
};

type LoginPayload = {
  username: string;
  password: string;
};

type AuthContextValue = {
  auth: AuthState | null;
  isAuthenticated: boolean;
  login: (payload: LoginPayload) => Promise<AuthState>;
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
          role: AuthRole;
          student_id: number | null;
          display_name: string | null;
        }>("/auth/login", {
          method: "POST",
          body: payload,
        });

        const nextState: AuthState = {
          accessToken: response.access_token,
          role: response.role,
          studentId: response.student_id ?? null,
          displayName: response.display_name ?? null,
        };
        setAuth(nextState);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
        return nextState;
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
