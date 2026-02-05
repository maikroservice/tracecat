"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import {
  CheckCircleIcon,
  GitPullRequestIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react"
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
import { validateGitLabUrl } from "@/lib/git"
import {
  useGitLabTestConnection,
  useWorkspaceManager,
  useWorkspaceSettings,
} from "@/lib/hooks"

const gitlabWorkspaceSyncSchema = z.object({
  workspace_id: z.string().min(1, "Please select a workspace"),
  git_repo_url: z
    .string()
    .min(1, "Repository URL is required")
    .superRefine((url, ctx) => validateGitLabUrl(url, ctx)),
})

type GitLabWorkspaceSyncForm = z.infer<typeof gitlabWorkspaceSyncSchema>

export function GitLabWorkspaceSync() {
  const { workspaces, workspacesIsLoading, workspacesError } =
    useWorkspaceManager()
  const [selectedWorkspace, setSelectedWorkspace] =
    useState<WorkspaceRead | null>(null)
  const [pullDialogOpen, setPullDialogOpen] = useState(false)
  const [selectedBranch, setSelectedBranch] = useState<string>("main")

  const { updateWorkspace, isUpdating } = useWorkspaceSettings(
    selectedWorkspace?.id ?? "",
    () => {}
  )

  const {
    testConnection,
    isTestingConnection,
    testConnectionData,
  } = useGitLabTestConnection()

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
    // Reset test connection data when workspace changes
    testConnection.reset()
  }

  const handleTestConnection = async () => {
    const gitRepoUrl = form.getValues("git_repo_url")

    // Validate URL first
    const result = gitlabWorkspaceSyncSchema.safeParse({
      workspace_id: form.getValues("workspace_id"),
      git_repo_url: gitRepoUrl,
    })

    if (!result.success) {
      // Trigger form validation to show error
      form.trigger("git_repo_url")
      return
    }

    testConnection.mutate({ git_repo_url: gitRepoUrl })
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
  const branches = testConnectionData?.branches ?? []
  const hasValidConnection = testConnectionData?.success === true

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
                      <div className="flex gap-2">
                        <FormControl>
                          <Input
                            placeholder="https://gitlab.com/my-org/my-repo.git"
                            className="max-w-md"
                            {...field}
                            onChange={(e) => {
                              field.onChange(e)
                              // Reset connection test when URL changes
                              testConnection.reset()
                            }}
                          />
                        </FormControl>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleTestConnection}
                          disabled={isTestingConnection || !field.value}
                        >
                          {isTestingConnection ? (
                            <>
                              <Loader2Icon className="mr-2 size-4 animate-spin" />
                              Testing...
                            </>
                          ) : (
                            "Test connection"
                          )}
                        </Button>
                      </div>
                      <FormDescription>
                        Git URL of the GitLab repository. Supports{" "}
                        <span className="font-mono tracking-tighter">
                          https://
                        </span>{" "}
                        or{" "}
                        <span className="font-mono tracking-tighter">
                          git+ssh://
                        </span>{" "}
                        schemes.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Connection Test Result */}
                {testConnectionData && (
                  <div
                    className={`rounded-lg border p-4 ${
                      testConnectionData.success
                        ? "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/50"
                        : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/50"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {testConnectionData.success ? (
                        <CheckCircleIcon className="size-5 text-green-500 mt-0.5" />
                      ) : (
                        <XCircleIcon className="size-5 text-red-500 mt-0.5" />
                      )}
                      <div className="flex-1">
                        <h4
                          className={`text-sm font-medium ${
                            testConnectionData.success
                              ? "text-green-800 dark:text-green-200"
                              : "text-red-800 dark:text-red-200"
                          }`}
                        >
                          {testConnectionData.success
                            ? "Connection successful"
                            : "Connection failed"}
                        </h4>
                        {testConnectionData.success ? (
                          <div className="mt-1 text-sm text-green-700 dark:text-green-300 space-y-1">
                            <p>Project: {testConnectionData.project_name}</p>
                            <p>
                              Default branch: {testConnectionData.default_branch}
                            </p>
                            <p>
                              {testConnectionData.branch_count} branch
                              {testConnectionData.branch_count !== 1 ? "es" : ""}{" "}
                              available
                            </p>
                          </div>
                        ) : (
                          <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                            {testConnectionData.error}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Branch Selection - only show when connection is successful */}
                {hasValidConnection && branches.length > 0 && (
                  <FormItem>
                    <FormLabel>Default branch</FormLabel>
                    <Select
                      value={selectedBranch}
                      onValueChange={setSelectedBranch}
                    >
                      <FormControl>
                        <SelectTrigger className="max-w-md">
                          <SelectValue placeholder="Select a branch" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {branches.map((branch) => (
                          <SelectItem key={branch} value={branch}>
                            {branch}
                            {branch === testConnectionData?.default_branch && (
                              <span className="ml-2 text-xs text-muted-foreground">
                                (default)
                              </span>
                            )}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Select the branch to pull workflows from
                    </FormDescription>
                  </FormItem>
                )}

                <Button
                  type="submit"
                  disabled={isUpdating || !hasValidConnection}
                >
                  {isUpdating ? "Saving..." : "Save configuration"}
                </Button>

                {!hasValidConnection && form.getValues("git_repo_url") && (
                  <p className="text-sm text-muted-foreground">
                    Test the connection before saving to verify access to the
                    repository.
                  </p>
                )}
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
