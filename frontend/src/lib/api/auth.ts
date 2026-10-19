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
