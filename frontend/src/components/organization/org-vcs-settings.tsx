"use client"

import { GitHubAppSetup } from "@/components/organization/org-vcs-github"
import { GitLabSetup } from "@/components/organization/org-vcs-gitlab"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export function OrgVCSSettings() {
  return (
    <div className="space-y-8">
      <Tabs defaultValue="github" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="github">GitHub</TabsTrigger>
          <TabsTrigger value="gitlab">GitLab</TabsTrigger>
        </TabsList>
        <TabsContent value="github" className="mt-4">
          <GitHubAppSetup />
        </TabsContent>
        <TabsContent value="gitlab" className="mt-4">
          <GitLabSetup />
        </TabsContent>
      </Tabs>
    </div>
  )
}
