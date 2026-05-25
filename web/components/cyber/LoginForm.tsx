"use client";

import { LockKeyhole } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";

import { CyberButton, CyberCard, CyberInput } from "@/components/cyber";
import { clientApiFetch } from "@/lib/client-api";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await clientApiFetch<{ ok: boolean }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      router.push(searchParams.get("next") ?? "/dashboard");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <CyberCard variant="terminal">
      <form onSubmit={submit} className="space-y-5">
        <div className="flex items-center gap-3 text-primary">
          <LockKeyhole className="h-5 w-5" />
          <span className="font-label text-sm uppercase">authentication required</span>
        </div>
        <CyberInput
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoFocus
          required
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
        <CyberButton className="w-full" variant="glitch" loading={loading}>
          login
        </CyberButton>
      </form>
    </CyberCard>
  );
}
