"use client";

import { Zap } from "lucide-react";
import { useState } from "react";

import { CyberButton } from "@/components/cyber/CyberButton";
import { Toast } from "@/components/ui/toast";
import { clientApiFetch } from "@/lib/client-api";
import type { SerperEstimate, SerperRunStarted } from "@/lib/types";

type SerperSearchButtonProps = {
  estimate: SerperEstimate;
};

export function SerperSearchButton({ estimate }: SerperSearchButtonProps) {
  const [loading, setLoading] = useState(false);
  const [started, setStarted] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [tone, setTone] = useState<"success" | "error">("success");

  async function startSearch() {
    setLoading(true);
    setMessage(null);
    try {
      const result = await clientApiFetch<SerperRunStarted>("/api/search/serper", {
        method: "POST",
      });
      setStarted(true);
      setTone("success");
      setMessage(
        `Serper run #${result.run_id} started: ${result.page_request_count} paid page requests queued.`
      );
    } catch (error) {
      setTone("error");
      setMessage(error instanceof Error ? error.message : "failed to start Serper search");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2 md:items-end">
      <CyberButton
        type="button"
        variant="secondary"
        loading={loading}
        disabled={started}
        onClick={startSearch}
        className="h-11"
      >
        {!loading && <Zap className="size-4" aria-hidden="true" />}
        serper boost
      </CyberButton>
      <p className="max-w-xs text-left font-label text-[0.68rem] uppercase leading-5 text-muted-foreground md:text-right">
        {estimate.query_count} queries / {estimate.page_request_count} paid page requests
      </p>
      <Toast message={message} tone={tone} />
    </div>
  );
}
