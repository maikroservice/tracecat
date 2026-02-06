"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import {
  CheckCircleIcon,
  CircleIcon,
  GitPullRequestIcon,
  Loader2Icon,
  RefreshCwIcon,
  XCircleIcon,
} from "lucide-react"
import { useCallback, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import type { WorkspaceRead } from "@/client"
import { CenteredSpinner } from "@/components/loading/spinner"
import { AlertNotification } from "@/components/notifications"
import { WorkflowPullDialog } from "@/components/organization/workflow-pull-dialog"
import { Badge } from "@/components/ui/badge"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { validateGitLabUrl } from "@/lib/git"
import {
  type GitLabTestConnectionResponse,
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
  default_branch: z.string().default("main"),
})

type GitLabWorkspaceSyncForm = z.infer<typeof gitlabWorkspaceSyncSchema>

type ConnectionStatusMap = Record<string, {
  status: "idle" | "testing" | "success" | "error"
  data?: GitLabTestConnectionResponse
}>

export function GitLabWorkspaceSync() {
  const { workspaces, workspacesIsLoading, workspacesError, refetchWorkspaces } =
    useWorkspaceManager()
  const [selectedWorkspace, setSelectedWorkspace] =
    useState<WorkspaceRead | null>(null)
  const [pullDialogOpen, setPullDialogOpen] = useState(false)
  const [selectedBranch, setSelectedBranch] = useState<string>("main")
  const [connectionStatuses, setConnectionStatuses] = useState<ConnectionStatusMap>({})

  const { updateWorkspace, isUpdating } = useWorkspaceSettings(
    selectedWorkspace?.id ?? "",
    () => {
      refetchWorkspaces()
    }
  )

  const { testConnection, isTestingConnection } = useGitLabTestConnection()

  const form = useForm<GitLabWorkspaceSyncForm>({
    resolver: zodResolver(gitlabWorkspaceSyncSchema),
    defaultValues: {
      workspace_id: "",
      git_repo_url: "",
      default_branch: "main",
    },
  })

  const handleWorkspaceChange = (workspaceId: string) => {
    const workspace = workspaces?.find((w) => w.id === workspaceId) ?? null
    setSelectedWorkspace(workspace)
    form.setValue("workspace_id", workspaceId)
    form.setValue("git_repo_url", workspace?.settings?.git_repo_url ?? "")
    // Set branch from connection status if available, otherwise default
    const status = connectionStatuses[workspaceId]
    if (status?.data?.default_branch) {
      setSelectedBranch(status.data.default_branch)
      form.setValue("default_branch", status.data.default_branch)
    } else {
      setSelectedBranch("main")
      form.setValue("default_branch", "main")
    }
  }

  const handleTestConnection = async () => {
    const gitRepoUrl = form.getValues("git_repo_url")
    const workspaceId = form.getValues("workspace_id")

    // Validate URL first
    const result = gitlabWorkspaceSyncSchema.safeParse({
      workspace_id: workspaceId,
      git_repo_url: gitRepoUrl,
      default_branch: "main",
    })

    if (!result.success) {
      form.trigger("git_repo_url")
      return
    }

    setConnectionStatuses((prev) => ({
      ...prev,
      [workspaceId]: { status: "testing" },
    }))

    testConnection.mutate(
      { git_repo_url: gitRepoUrl },
      {
        onSuccess: (data) => {
          setConnectionStatuses((prev) => ({
            ...prev,
            [workspaceId]: {
              status: data.success ? "success" : "error",
              data,
            },
          }))
          if (data.success && data.default_branch) {
            setSelectedBranch(data.default_branch)
            form.setValue("default_branch", data.default_branch)
          }
        },
        onError: () => {
          setConnectionStatuses((prev) => ({
            ...prev,
            [workspaceId]: {
              status: "error",
              data: { success: false, branches: [], branch_count: 0, error: "Connection failed" },
            },
          }))
        },
      }
    )
  }

  const handleTestWorkspaceConnection = useCallback(
    (workspace: WorkspaceRead) => {
      const gitRepoUrl = workspace.settings?.git_repo_url
      if (!gitRepoUrl) return

      setConnectionStatuses((prev) => ({
        ...prev,
        [workspace.id]: { status: "testing" },
      }))

      testConnection.mutate(
        { git_repo_url: gitRepoUrl },
        {
          onSuccess: (data) => {
            setConnectionStatuses((prev) => ({
              ...prev,
              [workspace.id]: {
                status: data.success ? "success" : "error",
                data,
              },
            }))
          },
          onError: () => {
            setConnectionStatuses((prev) => ({
              ...prev,
              [workspace.id]: {
                status: "error",
                data: { success: false, branches: [], branch_count: 0, error: "Connection failed" },
              },
            }))
          },
        }
      )
    },
    [testConnection]
  )

  const handleTestAllConnections = useCallback(() => {
    const workspacesWithUrls = workspaces?.filter(
      (w) => w.settings?.git_repo_url
    ) ?? []

    for (const workspace of workspacesWithUrls) {
      handleTestWorkspaceConnection(workspace)
    }
  }, [workspaces, handleTestWorkspaceConnection])

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
  const currentConnectionStatus = selectedWorkspace
    ? connectionStatuses[selectedWorkspace.id]
    : undefined
  const branches = currentConnectionStatus?.data?.branches ?? []
  const hasValidConnection = currentConnectionStatus?.status === "success"

  // Get workspaces with configured Git URLs for the overview
  const configuredWorkspaces = workspaces?.filter(
    (w) => w.settings?.git_repo_url
  ) ?? []

  const getStatusIcon = (workspaceId: string) => {
    const status = connectionStatuses[workspaceId]
    if (!status || status.status === "idle") {
      return <CircleIcon className="size-4 text-muted-foreground" />
    }
    if (status.status === "testing") {
      return <Loader2Icon className="size-4 animate-spin text-blue-500" />
    }
    if (status.status === "success") {
      return <CheckCircleIcon className="size-4 text-green-500" />
    }
    return <XCircleIcon className="size-4 text-red-500" />
  }

  const getStatusText = (workspaceId: string) => {
    const status = connectionStatuses[workspaceId]
    if (!status || status.status === "idle") return "Not tested"
    if (status.status === "testing") return "Testing..."
    if (status.status === "success") return "Connected"
    return status.data?.error || "Failed"
  }

  return (
    <div className="space-y-6">
      {/* Workspace Overview */}
      {configuredWorkspaces.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Workspace connections overview</CardTitle>
                <CardDescription>
                  Overview of all workspaces with configured GitLab repositories
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleTestAllConnections}
                disabled={isTestingConnection}
              >
                <RefreshCwIcon className={`mr-2 size-4 ${isTestingConnection ? "animate-spin" : ""}`} />
                Test all connections
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Workspace</TableHead>
                  <TableHead>Repository URL</TableHead>
                  <TableHead>Branch</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {configuredWorkspaces.map((workspace) => {
                  const status = connectionStatuses[workspace.id]
                  const defaultBranch = status?.data?.default_branch
                  return (
                    <TableRow key={workspace.id}>
                      <TableCell className="font-medium">
                        {workspace.name}
                      </TableCell>
                      <TableCell>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="font-mono text-xs truncate max-w-[300px] block">
                                {workspace.settings?.git_repo_url}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p className="font-mono text-xs">
                                {workspace.settings?.git_repo_url}
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>
                      <TableCell>
                        {defaultBranch ? (
                          <Badge variant="secondary" className="font-mono text-xs">
                            {defaultBranch}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {getStatusIcon(workspace.id)}
                          <span className="text-xs">
                            {getStatusText(workspace.id)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleTestWorkspaceConnection(workspace)}
                          disabled={connectionStatuses[workspace.id]?.status === "testing"}
                        >
                          {connectionStatuses[workspace.id]?.status === "testing" ? (
                            <Loader2Icon className="size-4 animate-spin" />
                          ) : (
                            <RefreshCwIcon className="size-4" />
                          )}
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Configuration Form */}
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
                                if (selectedWorkspace) {
                                  setConnectionStatuses((prev) => ({
                                    ...prev,
                                    [selectedWorkspace.id]: { status: "idle" },
                                  }))
                                }
                              }}
                            />
                          </FormControl>
                          <Button
                            type="button"
                            variant="outline"
                            onClick={handleTestConnection}
                            disabled={isTestingConnection || !field.value}
                          >
                            {currentConnectionStatus?.status === "testing" ? (
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
                  {currentConnectionStatus?.data && (
                    <div
                      className={`rounded-lg border p-4 ${
                        currentConnectionStatus.data.success
                          ? "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/50"
                          : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/50"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        {currentConnectionStatus.data.success ? (
                          <CheckCircleIcon className="size-5 text-green-500 mt-0.5" />
                        ) : (
                          <XCircleIcon className="size-5 text-red-500 mt-0.5" />
                        )}
                        <div className="flex-1">
                          <h4
                            className={`text-sm font-medium ${
                              currentConnectionStatus.data.success
                                ? "text-green-800 dark:text-green-200"
                                : "text-red-800 dark:text-red-200"
                            }`}
                          >
                            {currentConnectionStatus.data.success
                              ? "Connection successful"
                              : "Connection failed"}
                          </h4>
                          {currentConnectionStatus.data.success ? (
                            <div className="mt-1 text-sm text-green-700 dark:text-green-300 space-y-1">
                              <p>Project: {currentConnectionStatus.data.project_name}</p>
                              <p>
                                Default branch: {currentConnectionStatus.data.default_branch}
                              </p>
                              <p>
                                {currentConnectionStatus.data.branch_count} branch
                                {currentConnectionStatus.data.branch_count !== 1 ? "es" : ""}{" "}
                                available
                              </p>
                            </div>
                          ) : (
                            <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                              {currentConnectionStatus.data.error}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Branch Selection - only show when connection is successful */}
                  {hasValidConnection && branches.length > 0 && (
                    <FormField
                      control={form.control}
                      name="default_branch"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Default branch</FormLabel>
                          <Select
                            value={field.value || selectedBranch}
                            onValueChange={(value) => {
                              field.onChange(value)
                              setSelectedBranch(value)
                            }}
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
                                  {branch === currentConnectionStatus?.data?.default_branch && (
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
                    />
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
    </div>
  )
}
