import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createSdkClient } from "@/lib/sdk";

export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  try {
    const formData = await request.formData();
    const authToken = getAuthToken(cookies);
    const sdk = createSdkClient(authToken);

    // Get current workspace
    const workspace = await sdk.workspaces.getCurrent();

    if (!workspace) {
      console.error("[site/update] No active workspace");
      return redirect("/publishing/site?error=true", 303);
    }

    // Parse JSON fields
    let socialJson = null;
    try {
      const socialStr = formData.get("site_social_json") as string;
      if (socialStr?.trim()) {
        socialJson = JSON.parse(socialStr);
      }
    } catch (e) {
      console.error("[site/update] Invalid social JSON:", e);
      return redirect("/publishing/site?error=true", 303);
    }

    let metadataJson = null;
    try {
      const metadataStr = formData.get("site_metadata_json") as string;
      if (metadataStr?.trim()) {
        metadataJson = JSON.parse(metadataStr);
      }
    } catch (e) {
      console.error("[site/update] Invalid metadata JSON:", e);
      return redirect("/publishing/site?error=true", 303);
    }

    // Build update payload
    const updates = {
      site_title: formData.get("site_title") || null,
      site_tagline: formData.get("site_tagline") || null,
      site_description: formData.get("site_description") || null,
      site_canonical_url: formData.get("site_canonical_url") || null,
      site_logo: formData.get("site_logo") || null,
      site_favicon: formData.get("site_favicon") || null,
      site_locale: formData.get("site_locale") || "en-US",
      site_timezone: formData.get("site_timezone") || "America/New_York",
      site_contact_email: formData.get("site_contact_email") || null,
      site_social_json: socialJson,
      site_metadata_json: metadataJson,
    };

    // Update via SDK
    await sdk.workspaces.updatePreferences(workspace.id, updates);

    return redirect("/publishing/site?success=true", 303);
  } catch (error) {
    console.error("[site/update] Error:", error);
    return redirect("/publishing/site?error=true", 303);
  }
};
