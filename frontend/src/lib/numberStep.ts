// The `step` for a number field's input. A browser only accepts values a whole number of steps from the field's minimum (or from 0), so a
// default of 1 rejects 0.175 with "the two nearest valid values are 0 and 1". With no step set, "any" takes whatever decimal is typed;
// a field that sets a step (a schema field's `step`) keeps it.
export function numberStep(step: number | null | undefined): number | "any" {
  return typeof step === "number" && Number.isFinite(step) && step > 0 ? step : "any";
}
