/**
 * The "Statuses" filter on Assets and Resources, where trashed items are listed beside live ones: "All Statuses"
 * shows everything but the Trash — except inside the Trash group, which is there to list it — and "In the Trash"
 * shows only trashed items, in either view. (Entries does the same with its real statuses.)
 */
export const TRASHED = "trashed";

export function showsForStatus(statusQuery: string, trashed: boolean, inTrashGroup: boolean): boolean {
  return statusQuery === TRASHED ? trashed : !trashed || inTrashGroup;
}
