import { fetchApi } from "./client";
import type { WizardDefinition } from "../wizard";

export interface WizardSummary {
  slug: string;
  name: string;
  description: string;
  steps: number;
  package: string;
  packageName: string;
}

export interface WizardRead extends WizardSummary {
  definition: WizardDefinition;
}

/** The guided setups this workspace's packages bring. */
export const listWizards = (authToken: string): Promise<WizardSummary[]> => fetchApi<WizardSummary[]>("/api/groups/wizards", {}, authToken);

/** One wizard with its steps, or null when there is none of that name. */
export async function getWizard(slug: string, authToken: string): Promise<WizardRead | null> {
  try {
    return await fetchApi<WizardRead>(`/api/groups/wizards/${encodeURIComponent(slug)}`, {}, authToken);
  } catch (e) {
    if (/404|No such wizard/i.test(e instanceof Error ? e.message : String(e))) return null;
    throw e;
  }
}
