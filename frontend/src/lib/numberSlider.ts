// The pure part of a number field's drag slider (components/schema-fields/NumberField.astro): where the thumb sits for what the box says, and
// what the box says for where the thumb was dragged. An empty box means "not set" (it inherits), so the slider can show that and the person can go back to it.

/** Where the thumb stands for the box's text: a number within the ends puts it there (set); an empty or unreadable box leaves it at `rest` (not set). */
export function sliderState(text: string | null | undefined, min: number, max: number, rest: number): { set: boolean; position: number } {
  const raw = String(text ?? "").trim();
  const value = raw === "" ? NaN : Number(raw);
  if (!Number.isFinite(value)) return { set: false, position: Math.min(max, Math.max(min, rest)) };
  return { set: true, position: Math.min(max, Math.max(min, value)) };
}

/** What the box says after the thumb is dragged to `position`: rounded to the field's step (so 0.1 + 0.2 does not show as 0.30000000000000004). */
export function boxText(position: number, step: number): string {
  const decimals = step > 0 && step < 1 ? Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)) : 0;
  return String(Number(position.toFixed(decimals)));
}

/** The step the slider moves in: the field's own, else a hundredth of its range, so a drag is smooth whatever the ends. */
export function sliderStep(step: number | null | undefined, min: number, max: number): number {
  return typeof step === "number" && Number.isFinite(step) && step > 0 ? step : Number(((max - min) / 100).toPrecision(2));
}

/** A meter's fill for a measured value: how far along from `min` to `max` (0 to 1), whether it is nearing the top (`warn`) or at it (`hot`), and
 *  whether there is a reading at all (an empty or unreadable value draws an empty bar, not a full or a zero one). */
export function meterState(value: unknown, min: number, max: number): { has: boolean; position: number; zone: "ok" | "warn" | "hot" } {
  const n = value === null || value === undefined || value === "" ? NaN : Number(value);
  if (!Number.isFinite(n) || !(max > min)) return { has: false, position: 0, zone: "ok" };
  const position = Math.min(1, Math.max(0, (n - min) / (max - min)));
  return { has: true, position, zone: position >= 0.95 ? "hot" : position >= 0.8 ? "warn" : "ok" };
}

/** Whether a number field shows a drag slider beside its box (and its up and down arrows). Any field with both ends gets one without being asked:
 *  you can go from a low number to a higher one, so you can drag it. `slider: false` opts a field out; `slider: true` asks for one where it would
 *  not come by itself (a read-only field). A read-only field, or one drawn as a meter, does not get one by itself: there is nothing to drag. */
export function sliderWanted(field: { slider?: boolean | null; meter?: boolean | null; readOnly?: boolean | null; min?: number | null; max?: number | null }): boolean {
  const ends = typeof field.min === "number" && typeof field.max === "number" && Number.isFinite(field.min) && Number.isFinite(field.max) && field.max > field.min;
  if (!ends || field.slider === false) return false;
  return field.slider === true || (!field.readOnly && !field.meter);
}
