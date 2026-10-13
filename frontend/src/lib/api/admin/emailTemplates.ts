/**
 * Admin Email Templates API - manage system-wide email templates
 */

import { fetchApi } from "../client";
import type {
  EmailTemplateCreate,
  EmailTemplateRead,
  EmailTemplateSummary,
  EmailTemplateUpdate,
} from "../emailTemplates";

/**
 * List all system-wide email templates
 */
export async function listSystemEmailTemplates(authToken?: string): Promise<EmailTemplateSummary[]> {
  return fetchApi<EmailTemplateSummary[]>(`/api/admin/email/templates`, { method: "GET" }, authToken);
}

/**
 * Get a specific system email template
 */
export async function getSystemEmailTemplate(templateId: string, authToken?: string): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(`/api/admin/email/templates/${templateId}`, { method: "GET" }, authToken);
}

/**
 * Create a new system email template
 */
export async function createSystemEmailTemplate(
  data: EmailTemplateCreate,
  authToken?: string,
): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(
    `/api/admin/email/templates`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    },
    authToken,
  );
}

/**
 * Update a system email template
 */
export async function updateSystemEmailTemplate(
  templateId: string,
  data: EmailTemplateUpdate,
  authToken?: string,
): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(
    `/api/admin/email/templates/${templateId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    },
    authToken,
  );
}

/**
 * Delete a system email template
 */
export async function deleteSystemEmailTemplate(templateId: string, authToken?: string): Promise<void> {
  await fetchApi<void>(`/api/admin/email/templates/${templateId}`, { method: "DELETE" }, authToken);
}

/**
 * Send a test email using a system template
 */
export async function sendSystemTemplateTestEmail(
  templateId: string,
  recipientEmail: string,
  authToken?: string,
): Promise<{ message: string }> {
  return fetchApi<{ message: string }>(
    `/api/admin/email/templates/${templateId}/test`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipient_email: recipientEmail }),
    },
    authToken,
  );
}
