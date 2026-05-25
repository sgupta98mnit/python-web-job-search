import { ApplicationDetailClient } from "@/components/cyber/ApplicationDetailClient";
import { apiFetch, serverCookieHeader } from "@/lib/api";
import type { ApplicationDetail, ResumeVersionSummary } from "@/lib/types";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ApplicationDetailPage({ params }: PageProps) {
  const { id } = await params;
  const cookie = await serverCookieHeader();
  const [application, resumes] = await Promise.all([
    apiFetch<ApplicationDetail>(`/api/applications/${id}`, { cookie }),
    apiFetch<ResumeVersionSummary[]>(`/api/applications/${id}/resumes`, { cookie }),
  ]);
  return <ApplicationDetailClient application={application} initialResumes={resumes} />;
}
