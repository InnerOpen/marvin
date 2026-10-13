import type { APIRoute } from "astro";
import { getAuthToken } from "@/lib/api/client";
import { createSdkClient } from "@/lib/sdk";

export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  try {
    const formData = await request.formData();
    const authToken = getAuthToken(cookies);
    const sdk = createSdkClient(authToken);

    await sdk.user.updateProfile({
      fullName: formData.get("full_name") as string,
      email: formData.get("email") as string,
      username: formData.get("username") as string,
    });

    return redirect("/user/profile?success=true", 303);
  } catch (_error) {
    return redirect("/user/profile?error=true", 303);
  }
};
