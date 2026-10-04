/**
 * Form helpers shared by the create and edit collection forms.
 */

/** Form field emitted by CollectionVisibilityField. */
export const IS_PUBLIC_FIELD = "is_public";

/**
 * Read the "Visible to sites" checkbox. An unchecked checkbox is absent from FormData, so absence
 * must mean private — falling back to the API default (public) would make the toggle a no-op.
 */
export function isPublicFromForm(formData: FormData): boolean {
  return formData.get(IS_PUBLIC_FIELD) === "true";
}
