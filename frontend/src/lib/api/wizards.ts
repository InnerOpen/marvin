import { fetchApi } from "./client";
import type { WizardButton, WizardDefinition } from "../wizard";

export interface WizardSummary {
  slug: string;
  name: string;
  description: string;
  steps: number;
  package: string;
  packageName: string;
  /** Where an entry's page offers this setup, when the wizard says so. */
  button?: WizardButton | null;
}

export interface WizardRead extends WizardSummary {
  definition: WizardDefinition;
}

/** The guided setups this workspace's packages bring; with an entry type, only those with a button on that type's entries. */
export const listWizards = (authToken: string, entryType?: string): Promise<WizardSummary[]> =>
  fetchApi<WizardSummary[]>(`/api/groups/wizards${entryType ? `?entry_type=${encodeURIComponent(entryType)}` : ""}`, {}, authToken);

/** One wizard with its steps, or null when there is none of that name. */
export async function getWizard(slug: string, authToken: string): Promise<WizardRead | null> {
  try {
    return await fetchApi<WizardRead>(`/api/groups/wizards/${encodeURIComponent(slug)}`, {}, authToken);
  } catch (e) {
    if (/404|No such wizard/i.test(e instanceof Error ? e.message : String(e))) return null;
    throw e;
  }
}
