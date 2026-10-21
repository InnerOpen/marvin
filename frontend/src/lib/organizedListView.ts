// Wires a page's filter bar to the shared list kit and draws the sections (browser only; the logic it calls is in
// organizedList.ts and organizedListHtml.ts). Used with components/FilterBar.astro and components/OrganizedSections.astro.
//
//   const list = mountOrganizedList({
//     host, emptyFiltered, emptyAll,           // OrganizedSections' elements
//     search, selects: { from, status, starts },   // FilterBar's inputs, keyed by filter id (from, status + facets)
//     items: () => workflows, adapter, integrations, noun: "workflow",
//     storageKey: "marvin.automation.workflows.filters",
//     linkedId, renderItem, afterRender,
//     removedDelete: { kind: "workflows", canDelete },   // "Delete all of these" (admins), see removedDelete below
//   });
//   list.refresh();   // after the items change

import { deleteRemovedIntegrationItems, type RemovedKind } from "./api/removedIntegration.ts";
import {
  browserStore,
  type Integrations,
  type ListAdapter,
  loadFilters,
  organize,
  removedItems,
  saveFilters,
} from "./organizedList.ts";
import { removedConfirmHtml, type SectionsOptions, sectionsHtml } from "./organizedListHtml.ts";

export interface MountOptions<T> {
  host: HTMLElement;
  /** "No workflow matches…": shown when items exist but the filters hide them all. */
  emptyFiltered: HTMLElement;
  /** "No workflows yet…": shown when there are no items at all. */
  emptyAll: HTMLElement;
  search: HTMLInputElement | null;
  /** Each filter's select by key: `from`, `status` and the adapter's facet ids. A missing one is not filtered on. */
  selects: Record<string, HTMLSelectElement | null>;
  items: () => T[];
  adapter: ListAdapter<T>;
  integrations: Integrations;
  noun: string;
  /** False when the items have no On/Off (the headings then leave out "N on"). */
  onOff?: boolean;
  /** localStorage key the From/Status/facet choices are remembered under, per page. */
  storageKey: string;
  linkedId?: string | null;
  renderItem: SectionsOptions<T>["renderItem"];
  /** "Delete all of these" on the From a removed integration section. Omit (or `canDelete: false`, for non-admins) and
   * the button is not drawn. `kind` names the server's list (DELETE /api/groups/removed-integration-items/{kind}).
   * The dialog lists every item in the section, filters aside. `onDeleted` defaults to reloading the page. */
  removedDelete?: { kind: RemovedKind; canDelete: boolean; onDeleted?: () => void };
  /** After every draw: attach the cards' handlers. */
  afterRender?: (host: HTMLElement) => void;
}

export function mountOrganizedList<T>(options: MountOptions<T>) {
  const { host, selects, adapter, storageKey } = options;
  const store = browserStore();

  const offered = (select: HTMLSelectElement | null) =>
    select ? Array.from(select.querySelectorAll("option"), (o) => o.value).filter(Boolean) : [];
  const allowed = Object.fromEntries(Object.entries(selects).map(([id, select]) => [id, offered(select)]));
  const remembered = loadFilters(store, storageKey, allowed);
  for (const [id, select] of Object.entries(selects)) if (select) select.value = remembered[id] ?? "";

  const filters = () => Object.fromEntries(Object.entries(selects).map(([id, select]) => [id, select?.value ?? ""]));

  function refresh() {
    const items = options.items();
    const result = organize(items, adapter, options.integrations, filters(), {
      query: options.search?.value ?? "",
      linkedId: options.linkedId,
    });
    host.innerHTML = sectionsHtml(result.sections, {
      noun: options.noun,
      onOff: options.onOff,
      integrations: options.integrations,
      linkedId: options.linkedId,
      id: adapter.id,
      removedAction: options.removedDelete?.canDelete === true,
      renderItem: options.renderItem,
    });
    options.emptyAll.toggleAttribute("hidden", items.length > 0);
    options.emptyFiltered.toggleAttribute("hidden", items.length === 0 || result.shown > 0);
    options.afterRender?.(host);
  }

  // "Delete all of these": a dialog listing the section's items, then one server call for the kind.
  function confirmRemovedDelete() {
    const rd = options.removedDelete;
    if (!rd?.canDelete) return;
    const names = removedItems(options.items(), adapter, options.integrations).map((item) => adapter.name(item));
    if (!names.length) return;
    const dialog = document.createElement("dialog");
    dialog.className = "org-confirm-dialog";
    dialog.innerHTML = removedConfirmHtml(names, options.noun);
    document.body.appendChild(dialog);
    const close = () => {
      dialog.close();
      dialog.remove();
    };
    dialog.querySelector(".org-confirm-cancel")?.addEventListener("click", close);
    dialog.addEventListener("cancel", () => dialog.remove());
    dialog.querySelector(".org-confirm-delete")?.addEventListener("click", async (event) => {
      const button = event.currentTarget as HTMLButtonElement;
      button.disabled = true;
      button.textContent = "Deleting…";
      try {
        await deleteRemovedIntegrationItems(rd.kind);
        close();
        (rd.onDeleted ?? (() => location.reload()))();
      } catch (e) {
        button.disabled = false;
        button.textContent = "Try again";
        let note = dialog.querySelector(".org-confirm-error");
        if (!note) {
          note = document.createElement("p");
          note.className = "org-confirm-error";
          dialog.querySelector("h3")?.after(note);
        }
        note.textContent = e instanceof Error ? e.message : "Could not delete.";
      }
    });
    dialog.showModal();
  }

  options.search?.addEventListener("input", refresh);
  for (const select of Object.values(selects)) {
    select?.addEventListener("change", () => {
      saveFilters(store, storageKey, filters());
      refresh();
    });
  }

  // The ⋯ menus: one open at a time; click elsewhere or Escape closes; a bottom sheet on phones (CSS).
  const closeMenus = (except?: Element | null) => {
    host.querySelectorAll<HTMLElement>(".org-more-wrap.open").forEach((wrap) => {
      if (wrap === except) return;
      wrap.classList.remove("open");
      wrap.querySelector(".org-menu")?.setAttribute("hidden", "");
      wrap.querySelector(".org-more")?.setAttribute("aria-expanded", "false");
    });
  };
  host.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    if (target.closest(".org-delete-removed")) {
      confirmRemovedDelete();
      return;
    }
    const more = target.closest<HTMLElement>(".org-more");
    if (more) {
      const wrap = more.closest<HTMLElement>(".org-more-wrap")!;
      closeMenus(wrap);
      const open = wrap.classList.toggle("open");
      wrap.querySelector(".org-menu")?.toggleAttribute("hidden", !open);
      more.setAttribute("aria-expanded", String(open));
      return;
    }
    // Choosing an item closes its menu (the page's own handler still runs); a click on the sheet's backdrop closes it.
    closeMenus();
  });
  document.addEventListener("click", (event) => {
    if (!host.contains(event.target as Node)) closeMenus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });

  return { refresh };
}
