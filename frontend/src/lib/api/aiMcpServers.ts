/**
 * External MCP servers + AI settings — SDK wrapper (platform.ai.mcpServers / platform.ai.settings).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 */

import type {
  AISettings,
  AISettingsUpdate,
  McpServer,
  McpServerCreate,
  McpServerTestResult,
  McpServerUpdate,
} from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type { McpServer, McpServerCreate, McpServerTestResult, McpServerUpdate };

export async function listMcpServers(authToken?: string): Promise<McpServer[]> {
  return createSdkClient(authToken).ai.mcpServers.list();
}

export async function createMcpServer(data: McpServerCreate, authToken?: string): Promise<McpServer> {
  return createSdkClient(authToken).ai.mcpServers.create(data);
}

export async function updateMcpServer(id: string, data: McpServerUpdate, authToken?: string): Promise<McpServer> {
  return createSdkClient(authToken).ai.mcpServers.update(id, data);
}

export async function deleteMcpServer(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).ai.mcpServers.delete(id);
}

export async function testMcpServer(id: string, authToken?: string): Promise<McpServerTestResult> {
  return createSdkClient(authToken).ai.mcpServers.test(id);
}

export async function getAiSettings(authToken?: string): Promise<AISettings> {
  return createSdkClient(authToken).ai.settings.get();
}

export async function setExternalMcpEnabled(enabled: boolean, authToken?: string): Promise<AISettings> {
  const data: AISettingsUpdate = { externalMcpEnabled: enabled };
  return createSdkClient(authToken).ai.settings.update(data);
}
