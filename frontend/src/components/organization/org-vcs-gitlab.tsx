"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { CheckCircleIcon, GitBranchIcon } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { CenteredSpinner } from "@/components/loading/spinner"
import { AlertNotification } from "@/components/notifications"
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { useToast } from "@/components/ui/use-toast"
import { useGitLabCredentials, useGitLabCredentialsStatus } from "@/lib/hooks"

const gitLabCredentialsSchema = z.object({
  access_token: z.string().min(1, "Access token is required"),
  gitlab_url: z
    .string()
    .url("Please enter a valid URL")
    .refine(
      (url) => {
        try {
          const urlObj = new URL(url)
          return urlObj.protocol === "https:"
        } catch {
          return false
        }
      },
      {
        message: "Must be a valid HTTPS URL",
      }
    )
    .default("https://gitlab.com"),
})

type GitLabCredentialsFormData = z.infer<typeof gitLabCredentialsSchema>

export function GitLabSetup() {
  const {
    credentialsStatus,
    credentialsStatusIsLoading,
    credentialsStatusError,
    refetchCredentialsStatus,
  } = useGitLabCredentialsStatus()
  const { saveCredentials, deleteCredentials } = useGitLabCredentials()
  const [showSuccessMessage, setShowSuccessMessage] = useState(false)
  const { toast } = useToast()

  const form = useForm<GitLabCredentialsFormData>({
    resolver: zodResolver(gitLabCredentialsSchema),
    defaultValues: {
      access_token: "",
      gitlab_url: credentialsStatus?.gitlab_url || "https://gitlab.com",
    },
  })

  const onSubmit = async (data: GitLabCredentialsFormData) => {
    try {
      await saveCredentials.mutateAsync({
        access_token: data.access_token,
        gitlab_url: data.gitlab_url,
      })

      const action = credentialsStatus?.exists ? "updated" : "saved"
      toast({
        title: `GitLab credentials ${action} successfully`,
        description: `Your GitLab credentials have been ${action}.`,
      })

      // Clear sensitive data from form
      form.setValue("access_token", "")
      setShowSuccessMessage(true)
      refetchCredentialsStatus()
    } catch (error) {
      console.error("Failed to save GitLab credentials:", error)
      toast({
        title: "Error",
        description:
          error instanceof Error
            ? error.message
            : "Failed to save GitLab credentials",
        variant: "destructive",
      })
    }
  }

  const handleDelete = async () => {
    try {
      await deleteCredentials.mutateAsync()
      toast({
        title: "GitLab credentials deleted",
        description: "Your GitLab credentials have been removed.",
      })
      setShowSuccessMessage(false)
      refetchCredentialsStatus()
    } catch (error) {
      console.error("Failed to delete GitLab credentials:", error)
      toast({
        title: "Error",
        description:
          error instanceof Error
            ? error.message
            : "Failed to delete GitLab credentials",
        variant: "destructive",
      })
    }
  }

  if (credentialsStatusIsLoading) {
    return <CenteredSpinner />
  }

  if (credentialsStatusError) {
    return (
      <AlertNotification
        level="error"
        message={`Error loading GitLab credentials status: ${credentialsStatusError.message}`}
      />
    )
  }

  const buttonLabel = credentialsStatus?.exists
    ? "Update credentials"
    : "Save credentials"

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitBranchIcon className="size-5" />
          GitLab Setup
        </CardTitle>
        <CardDescription>
          Configure GitLab credentials to enable workflow synchronization with
          your GitLab repositories
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {showSuccessMessage && (
          <div className="rounded-md border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/50">
            <div className="flex">
              <CheckCircleIcon className="size-5 text-green-400" />
              <div className="ml-3">
                <h3 className="text-sm font-medium text-green-800 dark:text-green-200">
                  GitLab credentials configured successfully!
                </h3>
                <p className="mt-1 text-sm text-green-700 dark:text-green-300">
                  Your GitLab credentials have been saved. You can now use them
                  for workflow synchronization.
                </p>
              </div>
            </div>
          </div>
        )}

        {credentialsStatus?.exists && (
          <div className="rounded-md border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/50">
            <div className="flex">
              <CheckCircleIcon className="size-5 text-blue-400" />
              <div className="ml-3">
                <h3 className="text-sm font-medium text-blue-800 dark:text-blue-200">
                  GitLab credentials configured
                </h3>
                <p className="mt-1 text-sm text-blue-700 dark:text-blue-300">
                  GitLab URL: {credentialsStatus.gitlab_url}
                </p>
              </div>
            </div>
          </div>
        )}

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col"
          >
            <div className="space-y-8">
              <div className="space-y-2">
                <FormField
                  control={form.control}
                  name="gitlab_url"
                  render={({ field }) => (
                    <FormItem className="space-y-2">
                      <FormLabel>GitLab URL</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          placeholder="https://gitlab.com"
                          className="max-w-md"
                        />
                      </FormControl>
                      <p className="text-xs text-muted-foreground">
                        Use https://gitlab.com for GitLab.com or your
                        self-hosted GitLab instance URL
                      </p>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="access_token"
                  render={({ field }) => (
                    <FormItem className="space-y-2">
                      <FormLabel>Access Token *</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="password"
                          placeholder="glpat-xxxxxxxxxxxxxxxxxxxx"
                          className="max-w-md"
                        />
                      </FormControl>
                      <p className="text-xs text-muted-foreground">
                        Enter a Group Access Token or Personal Access Token with
                        api scope. Find this in GitLab → Settings → Access
                        Tokens.
                      </p>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="flex gap-2">
                <Button
                  type="submit"
                  disabled={saveCredentials.isPending}
                  className="min-w-32"
                >
                  {saveCredentials.isPending ? "Saving..." : buttonLabel}
                </Button>

                {credentialsStatus?.exists && (
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={handleDelete}
                    disabled={deleteCredentials.isPending}
                  >
                    {deleteCredentials.isPending ? "Deleting..." : "Delete"}
                  </Button>
                )}
              </div>
            </div>
          </form>
        </Form>

        {saveCredentials.isError && (
          <AlertNotification
            level="error"
            message={
              saveCredentials.error instanceof Error
                ? saveCredentials.error.message
                : "Failed to save GitLab credentials"
            }
          />
        )}
      </CardContent>
    </Card>
  )
}
