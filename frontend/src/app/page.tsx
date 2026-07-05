import { redirect } from "next/navigation";

// FE-01 replaces this with real session routing. Until then,
// point root to the login page to show off the elegant login experience.
export default function Home() {
  redirect("/login");
}
