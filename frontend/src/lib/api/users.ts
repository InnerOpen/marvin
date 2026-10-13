/**
 * Users API client - SDK wrapper
 * User profile and password management
 */

import { createSdkClient } from "../sdk";

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  fullName?: string | null;
  admin: boolean;
}

export interface UserProfileUpdate {
  username?: string;
  email?: string;
  fullName?: string | null;
}

export interface PasswordChange {
  currentPassword: string;
  newPassword: string;
}

/**
 * Get current user profile
 */
export async function getUserProfile(authToken: string): Promise<UserProfile> {
  const sdk = createSdkClient(authToken);
  return sdk.user.getProfile();
}

/**
 * Update current user profile
 */
export async function updateUserProfile(data: UserProfileUpdate, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.user.updateProfile(data);
}

/**
 * Change password
 */
export async function changePassword(data: PasswordChange, authToken: string): Promise<void> {
  const sdk = createSdkClient(authToken);
  return sdk.user.changePassword(data);
}
