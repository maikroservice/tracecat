"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { GitPullRequestIcon } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import type { WorkspaceRead } from "@/client"
import { CenteredSpinner } from "@/components/loading/spinner"
import { AlertNotification } from "@/components/notifications"
import { WorkflowPullDialog } from "@/components/organization/workflow-pull-dialog"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { validateGitSshUrl } from "@/lib/git"
import { useWorkspaceManager, useWorkspaceSettings } from "@/lib/hooks"

const gitlabWorkspaceSyncSchema = z.object({
  workspace_id: z.string().min(1, "Please select a workspace"),
  git_repo_url: z
    .string()
    .min(1, "Repository URL is required")
    .superRefine((url, ctx) => validateGitSshUrl(url, ctx)),
})

type GitLabWorkspaceSyncForm = z.infer<typeof gitlabWorkspaceSyncSchema>

export function GitLabWorkspaceSync() {
  const { workspaces, workspacesIsLoading, workspacesError } =
    useWorkspaceManager()
  const [selectedWorkspace, setSelectedWorkspace] =
    useState<WorkspaceRead | null>(null)
  const [pullDialogOpen, setPullDialogOpen] = useState(false)

  const { updateWorkspace, isUpdating } = useWorkspaceSettings(
    selectedWorkspace?.id ?? "",
    () => {}
  )

  const form = useForm<GitLabWorkspaceSyncForm>({
    resolver: zodResolver(gitlabWorkspaceSyncSchema),
    defaultValues: {
      workspace_id: "",
      git_repo_url: "",
    },
  })

  const handleWorkspaceChange = (workspaceId: string) => {
    const workspace = workspaces?.find((w) => w.id === workspaceId) ?? null
    setSelectedWorkspace(workspace)
    form.setValue("workspace_id", workspaceId)
    form.setValue("git_repo_url", workspace?.settings?.git_repo_url ?? "")
  }

  const onSubmit = async (values: GitLabWorkspaceSyncForm) => {
    if (!selectedWorkspace) return

    await updateWorkspace({
      settings: {
        git_repo_url: values.git_repo_url,
      },
    })

    // Update local state
    setSelectedWorkspace({
      ...selectedWorkspace,
      settings: {
        ...selectedWorkspace.settings,
        git_repo_url: values.git_repo_url,
      },
    })
  }

  if (workspacesIsLoading) {
    return <CenteredSpinner />
  }

  if (workspacesError) {
    return (
      <AlertNotification
        level="error"
        message={`Error loading workspaces: ${workspacesError.message}`}
      />
    )
  }

  const currentGitRepoUrl = selectedWorkspace?.settings?.git_repo_url

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace configuration</CardTitle>
        <CardDescription>
          Configure which GitLab repository to sync with each workspace
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="workspace_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Workspace</FormLabel>
                  <Select
                    onValueChange={handleWorkspaceChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger className="max-w-md">
                        <SelectValue placeholder="Select a workspace" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {workspaces?.map((workspace) => (
                        <SelectItem key={workspace.id} value={workspace.id}>
                          {workspace.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Select the workspace to configure GitLab sync for
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {selectedWorkspace && (
              <>
                <FormField
                  control={form.control}
                  name="git_repo_url"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>GitLab repository URL</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="git+ssh://git@gitlab.com/my-org/my-repo.git"
                          className="max-w-md"
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        Git URL of the GitLab repository. Must use{" "}
                        <span className="font-mono tracking-tighter">
                          git+ssh
                        </span>{" "}
                        scheme.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <Button type="submit" disabled={isUpdating}>
                  {isUpdating ? "Saving..." : "Save configuration"}
                </Button>
              </>
            )}
          </form>
        </Form>

        {/* Workflow Sync Section */}
        {selectedWorkspace && currentGitRepoUrl && (
          <div className="mt-6 p-4 border rounded-lg bg-muted/30">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h5 className="text-sm font-medium">
                  Workflow synchronization
                </h5>
                <p className="text-xs text-muted-foreground">
                  Pull workflow definitions from your GitLab repository into
                  this workspace
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPullDialogOpen(true)}
                className="flex items-center space-x-2"
              >
                <GitPullRequestIcon className="size-4" />
                <span>Pull workflows</span>
              </Button>
            </div>

            <div className="text-xs text-muted-foreground">
              <p>• Select a commit SHA to pull specific workflow versions</p>
              <p>
                • All changes are atomic - either all workflows import or none
                do
              </p>
            </div>
          </div>
        )}

        {selectedWorkspace && (
          <WorkflowPullDialog
            open={pullDialogOpen}
            onOpenChange={setPullDialogOpen}
            workspaceId={selectedWorkspace.id}
            gitRepoUrl={currentGitRepoUrl}
          />
        )}
      </CardContent>
    </Card>
  )
}
