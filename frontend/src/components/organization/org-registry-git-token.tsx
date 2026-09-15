"use client"

import {
  KeyRoundIcon,
  MoreHorizontalIcon,
  RefreshCcw,
  Trash2Icon,
} from "lucide-react"
import { type ReactNode, useState } from "react"
import { useScopeCheck } from "@/components/auth/scope-guard"
import { Spinner } from "@/components/loading/spinner"
import {
  CreateGitTokenDialog,
  CreateGitTokenDialogTrigger,
  GIT_TOKEN_SECRET_NAME,
} from "@/components/organization/org-git-token-dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { getApiErrorDetail } from "@/lib/errors"
import { useOrgSecrets } from "@/lib/hooks"

/**
 * Git access token section for the custom registry Repository page.
 *
 * Shows the `git-access-token` organization credential used to authenticate
 * `git+https` registry syncs and lets admins add, replace, or remove it.
 * Independent of the surrounding Git settings form.
 */
export function OrgRegistryGitTokenSection() {
  const canCreate = useScopeCheck("org:secret:create") === true
  const canUpdate = useScopeCheck("org:secret:update") === true
  const canDelete = useScopeCheck("org:secret:delete") === true
  const { orgSecrets, orgSecretsIsLoading, orgSecretsError, deleteSecretById } =
    useOrgSecrets()
  const [removeOpen, setRemoveOpen] = useState(false)
  const [replaceOpen, setReplaceOpen] = useState(false)

  const gitTokenSecret =
    orgSecrets?.find((secret) => secret.name === GIT_TOKEN_SECRET_NAME) ?? null

  async function handleConfirmRemove() {
    if (!gitTokenSecret) {
      return
    }
    try {
      await deleteSecretById(gitTokenSecret)
    } catch (error) {
      console.error("Failed to remove git access token", error)
    } finally {
      setRemoveOpen(false)
    }
  }

  const showAdd = canCreate && gitTokenSecret === null
  const showReplace = canUpdate && gitTokenSecret !== null

  let body: ReactNode
  if (orgSecretsIsLoading) {
    body = (
      <div className="flex items-center justify-center py-6">
        <Spinner className="size-4" />
      </div>
    )
  } else if (orgSecretsError) {
    body = (
      <p className="px-3 py-6 text-center text-sm text-destructive">
        {getApiErrorDetail(orgSecretsError) ?? "Couldn't load secrets."}
      </p>
    )
  } else if (!gitTokenSecret) {
    body = (
      <div className="flex items-center gap-3 px-3 py-2.5">
        <KeyRoundIcon className="size-4 shrink-0 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No git access token added
        </p>
      </div>
    )
  } else {
    body = (
      <div className="flex items-center gap-3 px-3 py-2.5">
        <KeyRoundIcon className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-mono text-sm">
              {gitTokenSecret.name}
            </span>
            <Badge variant="secondary" className="text-xs">
              In use
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            {gitTokenSecret.environment}
          </p>
        </div>
        {(showReplace || canDelete) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label="Git access token actions"
              >
                <MoreHorizontalIcon className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {showReplace && (
                <DropdownMenuItem onSelect={() => setReplaceOpen(true)}>
                  <RefreshCcw className="mr-2 size-4" />
                  Replace token
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem
                  onSelect={() => setRemoveOpen(true)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2Icon className="mr-2 size-4" />
                  Remove
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm font-medium leading-none">Git access token</p>
          {showAdd && (
            <CreateGitTokenDialog>
              <CreateGitTokenDialogTrigger asChild>
                <Button type="button" variant="outline" size="sm">
                  Add git access token
                </Button>
              </CreateGitTokenDialogTrigger>
            </CreateGitTokenDialog>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Tracecat uses this token to clone{" "}
          <span className="font-mono tracking-tighter">git+https</span>{" "}
          repositories. Not needed for{" "}
          <span className="font-mono tracking-tighter">git+ssh</span> origins or
          public repositories.
        </p>
      </div>
      <div className="rounded-md border">{body}</div>

      {showReplace && gitTokenSecret && (
        <CreateGitTokenDialog
          open={replaceOpen}
          onOpenChange={setReplaceOpen}
          existingSecret={gitTokenSecret}
        />
      )}

      <AlertDialog open={removeOpen} onOpenChange={setRemoveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove git access token?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes{" "}
              <span className="font-mono">{GIT_TOKEN_SECRET_NAME}</span>.
              Private git+https registry syncs fall back to anonymous access.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRemove}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Remove token
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
