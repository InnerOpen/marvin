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
import { createSdkClient } from "../sdk";
import { getServerApiBaseUrl } from "./config";

export type { AuthToken, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest, UserRegistration };

/**
 * Login with username and password
 */
export async function login(data: LoginRequest): Promise<AuthToken> {
  const authClient = createAuthClient(getServerApiBaseUrl());
  return authClient.login(data);
}

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
 * Reset password with token
 */
export async function resetPassword(data: ResetPasswordRequest): Promise<{ message: string }> {
  const authClient = createAuthClient(getServerApiBaseUrl());
  return authClient.resetPassword(data);
}

/**
 * Refresh access token
 */
export async function refreshToken(authToken: string): Promise<AuthToken> {
  const sdk = createSdkClient(authToken);
  return sdk.session.refresh();
}

/**
 * Logout current user
 */
export async function logout(authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.session.logout();
}
