"use client"

import { GitLabWorkspaceSync } from "@/components/organization/gitlab-workspace-sync"
import { GitLabSetup } from "@/components/organization/org-vcs-gitlab"

export default function GitLabVCSSettingsPage() {
  return (
    <div className="size-full overflow-auto">
      <div className="container flex h-full max-w-[1000px] flex-col space-y-12">
        <div className="flex w-full">
          <div className="items-start space-y-3 text-left">
            <h2 className="text-2xl font-semibold tracking-tight">
              GitLab workflow sync
            </h2>
            <p className="text-md text-muted-foreground">
              Sync workflows to and from your GitLab repositories.
            </p>
          </div>
        </div>

        <GitLabSetup />
        <GitLabWorkspaceSync />
      </div>
    </div>
  )
}
