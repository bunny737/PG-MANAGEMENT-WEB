import { redirect } from "next/navigation";

// FE-01 replaces this with real session routing (role-based redirect via
// /auth/me/). Until then, root always points at the Owner dashboard.
export default function Home() {
  redirect("/dashboard");
}
