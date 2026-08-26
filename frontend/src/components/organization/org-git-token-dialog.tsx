"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import type { DialogProps } from "@radix-ui/react-dialog"
import React from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import type { SecretReadMinimal } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
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
import { toast } from "@/components/ui/use-toast"
import { useOrgSecrets } from "@/lib/hooks"

/** Name of the org secret the registry sync reads for git+https auth. */
export const GIT_TOKEN_SECRET_NAME = "git-access-token"

const gitTokenSchema = z.object({
  token: z.string().min(1, "Token is required"),
  username: z
    .string()
    .default("")
    .transform((value) => value.trim()),
  environment: z
    .string()
    .nullable()
    .transform((value) => value || "default"),
})
type GitTokenForm = z.infer<typeof gitTokenSchema>

interface CreateGitTokenDialogProps
  extends DialogProps,
    React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode
  /** Existing git-access-token secret; when set, submitting replaces it. */
  existingSecret?: SecretReadMinimal
}

/**
 * Dialog for creating or replacing the `git-access-token` organization
 * credential used to authenticate git+https registry syncs.
 */
export function CreateGitTokenDialog({
  children,
  className,
  existingSecret,
}: CreateGitTokenDialogProps) {
  const [showDialog, setShowDialog] = React.useState(false)
  const { createSecret, updateSecretById } = useOrgSecrets()

  const methods = useForm<GitTokenForm>({
    mode: "onChange",
    resolver: zodResolver(gitTokenSchema),
    defaultValues: {
      token: "",
      username: "",
      environment: "default",
    },
  })

  const onSubmit = async (values: GitTokenForm) => {
    const keys = [{ key: "token", value: values.token }]
    if (values.username) {
      keys.push({ key: "username", value: values.username })
    }
    try {
      if (existingSecret) {
        await updateSecretById({
          secretId: existingSecret.id,
          params: { keys },
        })
      } else {
        await createSecret({
          type: "custom",
          name: GIT_TOKEN_SECRET_NAME,
          description: "HTTPS access token for git+https registry sync",
          environment: values.environment,
          keys,
        })
      }
      setShowDialog(false)
    } catch (error) {
      console.error(error)
    }
    methods.reset()
  }
  const onValidationFailed = () => {
    toast({
      title: "Form validation failed",
      description: "A validation error occurred while saving the token.",
    })
  }

  return (
    <Dialog open={showDialog} onOpenChange={setShowDialog}>
      {children}
      <DialogContent className={className}>
        <DialogHeader>
          <DialogTitle>
            {existingSecret
              ? "Replace git access token"
              : "Add git access token"}
          </DialogTitle>
          <div className="flex text-sm leading-relaxed text-muted-foreground">
            <span>
              Access token used to authenticate{" "}
              <span className="font-mono tracking-tighter">git+https</span>{" "}
              registry syncs, stored as the{" "}
              <span className="font-mono tracking-tighter">
                {GIT_TOKEN_SECRET_NAME}
              </span>{" "}
              organization credential.
            </span>
          </div>
        </DialogHeader>
        <Form {...methods}>
          <form
            onSubmit={methods.handleSubmit(onSubmit, onValidationFailed)}
            className="space-y-4"
          >
            <FormField
              control={methods.control}
              name="token"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Token</FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      autoComplete="off"
                      placeholder="glpat-..."
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    For GitLab, a project access token with the{" "}
                    <span className="font-mono tracking-tighter">
                      read_repository
                    </span>{" "}
                    scope is sufficient.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={methods.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username (optional)</FormLabel>
                  <FormControl>
                    <Input autoComplete="off" placeholder="oauth2" {...field} />
                  </FormControl>
                  <FormDescription>
                    Defaults to{" "}
                    <span className="font-mono tracking-tighter">oauth2</span>.
                    Use the token name for GitLab project access tokens, or the
                    generated username for deploy tokens.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            {!existingSecret && (
              <FormField
                control={methods.control}
                name="environment"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Environment</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="default"
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="ghost" type="button">
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit">
                {existingSecret ? "Replace token" : "Add token"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export const CreateGitTokenDialogTrigger = DialogTrigger
