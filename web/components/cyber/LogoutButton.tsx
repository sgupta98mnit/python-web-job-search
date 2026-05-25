"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CyberButton } from "@/components/cyber/CyberButton";
import { clientApiFetch } from "@/lib/client-api";

export function LogoutButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function logout() {
    setLoading(true);
    await clientApiFetch<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <CyberButton variant="outline" size="sm" onClick={logout} loading={loading}>
      <LogOut className="h-4 w-4" />
      logout
    </CyberButton>
  );
}
