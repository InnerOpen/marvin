/**
 * Authentication API
 * Migrated to use @inneropen/marvin-sdk
 */

import type {
  AuthToken,
  ForgotPasswordRequest,
  LoginRequest,
  ResetPasswordRequest,
  UserRegistration,
} from "@inneropen/marvin-sdk";
import { createAuthClient } from "@inneropen/marvin-sdk";
import { getServerApiBaseUrl } from "./config";

export type { AuthToken, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest, UserRegistration };

/**
 * Register a new user
 */
export async function register(data: UserRegistration): Promise<{ message: string; userId: string }> {
  const authClient = createAuthClient(getServerApiBaseUrl());
  return authClient.register(data);
}

/**
 * Request password reset
 */
export async function forgotPassword(data: ForgotPasswordRequest): Promise<{ message: string }> {
  const authClient = createAuthClient(getServerApiBaseUrl());
  return authClient.forgotPassword(data);
}

/**
 * Set a new password with the token from a reset email (the /reset-password page). Called straight at the API: the
 * SDK's resetPassword sent a shape the API never took ({token, newPassword}) until its 2026-10-19 fix, and the
 * frontend's SDK is older than that.
 */
export async function resetPassword(token: string, password: string, passwordConfirm: string): Promise<{ message: string }> {
  const res = await fetch(`${getServerApiBaseUrl()}/api/users/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password, passwordConfirm }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // FastAPI's detail: a string from the service, or validation errors (a too-short password) as a list.
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => String(d?.msg ?? "").replace(/^Value error, /, "")).join(" ") : "";
    throw new Error(message || `Couldn't change the password (${res.status})`);
  }
  return body;
}
