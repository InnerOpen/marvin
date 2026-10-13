/**
 * Browser-side glue for <SubmissionProtectionFields>: wires the "use platform default" toggles and
 * reads the form back into the API shape. Shared by the admin page (concrete values) and the
 * workspace page (override, where an inherited field is sent as null).
 */

type Value = string | string[] | boolean | number | null;

function readControl(control: HTMLElement): Value {
  if (control instanceof HTMLSelectElement) return control.value;
  if (control instanceof HTMLTextAreaElement) {
    return control.value
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }
  if (control instanceof HTMLInputElement) {
    if (control.type === "checkbox") return control.checked;
    if (control.type === "number") return control.value.trim() === "" ? null : Number(control.value);
    return control.value;
  }
  return null;
}

function fields(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(".sp-field"));
}

function controlOf(field: HTMLElement): HTMLElement | null {
  return field.querySelector<HTMLElement>("[data-sp-control]");
}

function inheritToggleOf(field: HTMLElement): HTMLInputElement | null {
  return field.querySelector<HTMLInputElement>(".sp-inherit-toggle");
}

/** Enable/disable each control from its inherit toggle, and keep doing so on change. */
export function initSubmissionProtectionForm(root: HTMLElement, editable: boolean): void {
  for (const field of fields(root)) {
    const toggle = inheritToggleOf(field);
    const control = controlOf(field);
    if (!control) continue;
    const sync = () => {
      const inherited = toggle?.checked ?? false;
      (control as HTMLInputElement).disabled = !editable || inherited;
      field.classList.toggle("is-inherited", inherited);
    };
    toggle?.addEventListener("change", sync);
    sync();
  }
}

/** Read the form: `{ [field]: value }`; an inherited field reads as null. */
export function readSubmissionProtectionForm(root: HTMLElement): Record<string, Value> {
  const out: Record<string, Value> = {};
  for (const field of fields(root)) {
    const key = field.dataset.field;
    const control = controlOf(field);
    if (!key || !control) continue;
    out[key] = inheritToggleOf(field)?.checked ? null : readControl(control);
  }
  return out;
}
