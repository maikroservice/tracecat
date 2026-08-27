"use client"

import { KeyRoundIcon, PlusCircle, Trash2Icon } from "lucide-react"
import { ConfirmationDialog } from "@/components/confirmation-dialog"
import {
  CreateGitTokenDialog,
  CreateGitTokenDialogTrigger,
  GIT_TOKEN_SECRET_NAME,
} from "@/components/organization/org-git-token-dialog"
import { OrgSSHKeysTable } from "@/components/organization/org-secrets-table"
import {
  CreateSSHKeyDialog,
  CreateSSHKeyDialogTrigger,
} from "@/components/ssh-keys/ssh-key-create-dialog"
import { Button } from "@/components/ui/button"
import { useOrgSecrets } from "@/lib/hooks"

export default function SSHKeysPage() {
  const { createSecret, orgSecrets, deleteSecretById } = useOrgSecrets()
  const gitTokenSecret = orgSecrets?.find(
    (secret) => secret.name === GIT_TOKEN_SECRET_NAME
  )
  return (
    <div className="size-full overflow-auto">
      <div className="container flex h-full max-w-[1000px] flex-col space-y-12">
        <div className="flex w-full">
          <div className="items-start space-y-3 text-left">
            <h2 className="text-2xl font-semibold tracking-tight">
              Registry credentials
            </h2>
            <p className="text-md text-muted-foreground">
              View your organization-wide registry credentials here. Tracecat
              uses SSH keys to authenticate into git+ssh private action
              registries, and a git access token for git+https registries.
            </p>
          </div>
          <div className="ml-auto flex items-center space-x-2">
            <ConfirmationDialog
              title="Sync All Repositories"
              description="Are you sure you want to sync all repositories? This will replace all existing actions with the latest from the repositories."
              onConfirm={() => {}}
            ></ConfirmationDialog>
          </div>
        </div>
        <div className="space-y-4">
          <>
            <h6 className="text-sm font-semibold">Add secret</h6>
            <div className="flex items-center space-x-2">
              <CreateSSHKeyDialog handler={createSecret}>
                <CreateSSHKeyDialogTrigger asChild>
                  <Button
                    variant="outline"
                    role="combobox"
                    className="space-x-2"
                  >
                    <PlusCircle className="mr-2 size-4" />
                    Create new SSH key
                  </Button>
                </CreateSSHKeyDialogTrigger>
              </CreateSSHKeyDialog>
              <CreateGitTokenDialog existingSecret={gitTokenSecret}>
                <CreateGitTokenDialogTrigger asChild>
                  <Button variant="outline" className="space-x-2">
                    <KeyRoundIcon className="mr-2 size-4" />
                    {gitTokenSecret
                      ? "Replace git access token"
                      : "Add git access token"}
                  </Button>
                </CreateGitTokenDialogTrigger>
              </CreateGitTokenDialog>
              {gitTokenSecret && (
                <ConfirmationDialog
                  title="Remove git access token"
                  description="Are you sure you want to remove the git access token? Private git+https registry syncs will fall back to anonymous access."
                  onConfirm={() => deleteSecretById(gitTokenSecret)}
                >
                  <Button
                    variant="ghost"
                    className="space-x-2 text-muted-foreground"
                  >
                    <Trash2Icon className="mr-2 size-4" />
                    Remove git access token
                  </Button>
                </ConfirmationDialog>
              )}
            </div>
          </>
          <>
            <h6 className="text-sm font-semibold">Manage secrets</h6>
            <OrgSSHKeysTable />
          </>
        </div>
      </div>
    </div>
  )
}
