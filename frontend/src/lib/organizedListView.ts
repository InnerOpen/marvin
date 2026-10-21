// Wires a page's filter bar to the shared list kit and draws the sections (browser only; the logic it calls is in
// organizedList.ts and organizedListHtml.ts). Used with components/FilterBar.astro and components/OrganizedSections.astro.
//
//   const list = mountOrganizedList({
//     host, emptyFiltered, emptyAll,           // OrganizedSections' elements
//     search, selects: { from, status, starts },   // FilterBar's inputs, keyed by filter id (from, status + facets)
//     items: () => workflows, adapter, integrations, noun: "workflow",
//     storageKey: "marvin.automation.workflows.filters",
//     linkedId, renderItem, afterRender,
//   });
//   list.refresh();   // after the items change

import {
  browserStore,
  type Integrations,
  type ListAdapter,
  loadFilters,
  organize,
  saveFilters,
  urlFilters,
} from "./organizedList.ts";
import { type SectionsOptions, sectionsHtml } from "./organizedListHtml.ts";

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
  /** localStorage key the From/Status/facet choices are remembered under, per page. */
  storageKey: string;
  linkedId?: string | null;
  renderItem: SectionsOptions<T>["renderItem"];
  /** After every draw: attach the cards' handlers. */
  afterRender?: (host: HTMLElement) => void;
}

export function mountOrganizedList<T>(options: MountOptions<T>) {
  const { host, selects, adapter, storageKey } = options;
  const store = browserStore();

  const offered = (select: HTMLSelectElement | null) =>
    select ? Array.from(select.querySelectorAll("option"), (o) => o.value).filter(Boolean) : [];
  const allowed = Object.fromEntries(Object.entries(selects).map(([id, select]) => [id, offered(select)]));
  // The URL beats what was remembered (a link from another page, e.g. an integration's card, means "this one"),
  // and is not remembered itself: the next visit without it opens the way it was left.
  const remembered = { ...loadFilters(store, storageKey, allowed), ...urlFilters(location.search, allowed) };
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
      integrations: options.integrations,
      linkedId: options.linkedId,
      id: adapter.id,
      renderItem: options.renderItem,
    });
    options.emptyAll.toggleAttribute("hidden", items.length > 0);
    options.emptyFiltered.toggleAttribute("hidden", items.length === 0 || result.shown > 0);
    options.afterRender?.(host);
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
