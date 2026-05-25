import { Suspense } from "react";

import { GlitchHeading, LoginForm } from "@/components/cyber";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <GlitchHeading className="mb-6 text-center text-4xl">access node</GlitchHeading>
        <Suspense fallback={<div className="h-64 border border-border bg-card/70 cyber-chamfer" />}>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
