/**
 * The agent's bound tool surface — SDK wrapper (platform.ai.tools.listAgent).
 * Pass authToken in SSR (from Astro.cookies); omit it in the browser to use the HttpOnly cookie.
 */

import type { AgentToolInfo } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type { AgentToolInfo };

/** A bound tool as the server lists it today: the SDK's shape plus the permission-matrix fields. */
export type AgentTool = AgentToolInfo & {
  /** Its permission-matrix row (see services/ai/tools/categories.py). */
  category?: string | null;
  /** "Ask first": each call pauses the run for the user's approval. */
  asksFirst?: boolean;
};

/** Tools the bubble's Marvin actually binds for the caller (built-in + external MCP), through Marvin's matrix. */
export async function listAgentTools(authToken?: string): Promise<AgentTool[]> {
  return (await createSdkClient(authToken).ai.tools.listAgent()) as AgentTool[];
}
