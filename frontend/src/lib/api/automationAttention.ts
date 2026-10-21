/** GET /api/automations/attention (ADMIN and above; a 403 for anyone else). Pass authToken in SSR. */

import type { AutomationAttention } from "../automationAttention";
import { fetchApi } from "./client";

export const getAutomationAttention = (authToken?: string) =>
  fetchApi<AutomationAttention>("/api/automations/attention", {}, authToken);
