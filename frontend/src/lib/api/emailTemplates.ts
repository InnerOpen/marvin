/**
 * Email Templates API - manage workspace email templates
 */

import { fetchApi } from "./client";

export interface EmailTemplateSummary {
  id: string;
  template_type: string;
  workspace_id: string | null;
  name: string;
  description?: string;
  enabled: boolean;
  created_at: string;
  update_at: string;
}

export interface EmailTemplateRead {
  id: string;
  template_type: string;
  workspace_id: string | null;
  name: string;
  description?: string;
  subject: string;
  header_text?: string;
  message_top?: string;
  message_bottom?: string;
  button_text?: string;
  custom_html?: string;
  available_variables?: Record<string, string>;
  enabled: boolean;
  created_at: string;
  update_at: string;
}

export interface EmailTemplateCreate {
  template_type: string;
  workspace_id?: string;
  name: string;
  description?: string;
  subject: string;
  header_text?: string;
  message_top?: string;
  message_bottom?: string;
  button_text?: string;
  custom_html?: string;
  available_variables?: Record<string, string>;
  enabled?: boolean;
}

export interface EmailTemplateUpdate {
  name?: string;
  description?: string;
  subject?: string;
  header_text?: string;
  message_top?: string;
  message_bottom?: string;
  button_text?: string;
  custom_html?: string;
  available_variables?: Record<string, string>;
  enabled?: boolean;
}

/**
 * List all email templates for the workspace
 */
export async function listEmailTemplates(workspaceId: string, authToken?: string): Promise<EmailTemplateSummary[]> {
  return fetchApi<EmailTemplateSummary[]>(
    `/api/platform/workspaces/${workspaceId}/email-templates`,
    { method: "GET" },
    authToken,
  );
}

/**
 * Get a specific email template
 */
export async function getEmailTemplate(
  workspaceId: string,
  templateId: string,
  authToken?: string,
): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(
    `/api/platform/workspaces/${workspaceId}/email-templates/${templateId}`,
    { method: "GET" },
    authToken,
  );
}

/**
 * Create a new email template
 */
export async function createEmailTemplate(
  workspaceId: string,
  data: EmailTemplateCreate,
  authToken?: string,
): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(
    `/api/platform/workspaces/${workspaceId}/email-templates`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    },
    authToken,
  );
}

/**
 * Update an email template
 */
export async function updateEmailTemplate(
  workspaceId: string,
  templateId: string,
  data: EmailTemplateUpdate,
  authToken?: string,
): Promise<EmailTemplateRead> {
  return fetchApi<EmailTemplateRead>(
    `/api/platform/workspaces/${workspaceId}/email-templates/${templateId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    },
    authToken,
  );
}

/**
 * Delete an email template
 */
export async function deleteEmailTemplate(workspaceId: string, templateId: string, authToken?: string): Promise<void> {
  await fetchApi<void>(
    `/api/platform/workspaces/${workspaceId}/email-templates/${templateId}`,
    { method: "DELETE" },
    authToken,
  );
}
