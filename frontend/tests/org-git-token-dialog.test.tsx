import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { SecretReadMinimal } from "@/client"
import {
  CreateGitTokenDialog,
  CreateGitTokenDialogTrigger,
  GIT_TOKEN_SECRET_NAME,
} from "@/components/organization/org-git-token-dialog"

const createSecret = jest.fn()
const updateSecretById = jest.fn()

jest.mock("@/lib/hooks", () => ({
  useOrgSecrets: () => ({
    createSecret,
    updateSecretById,
  }),
}))

function renderDialog(existingSecret?: SecretReadMinimal) {
  return render(
    <CreateGitTokenDialog existingSecret={existingSecret}>
      <CreateGitTokenDialogTrigger asChild>
        <button type="button">Open</button>
      </CreateGitTokenDialogTrigger>
    </CreateGitTokenDialog>
  )
}

const existingSecret = {
  id: "secret-id-1",
  type: "custom",
  name: GIT_TOKEN_SECRET_NAME,
  description: null,
  keys: ["token"],
  environment: "default",
} as unknown as SecretReadMinimal

describe("CreateGitTokenDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it("creates the git-access-token secret with a token-only key set", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole("button", { name: "Open" }))
    await user.type(screen.getByLabelText("Token"), "glpat-test-token")
    await user.click(screen.getByRole("button", { name: "Add token" }))

    await waitFor(() => expect(createSecret).toHaveBeenCalledTimes(1))
    expect(createSecret).toHaveBeenCalledWith({
      type: "custom",
      name: GIT_TOKEN_SECRET_NAME,
      description: "HTTPS access token for git+https registry sync",
      environment: "default",
      keys: [{ key: "token", value: "glpat-test-token" }],
    })
    expect(updateSecretById).not.toHaveBeenCalled()
  })

  it("includes the username key only when a username is provided", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole("button", { name: "Open" }))
    await user.type(screen.getByLabelText("Token"), "glpat-test-token")
    await user.type(screen.getByLabelText("Username (optional)"), "deploy-user")
    await user.click(screen.getByRole("button", { name: "Add token" }))

    await waitFor(() => expect(createSecret).toHaveBeenCalledTimes(1))
    expect(createSecret.mock.calls[0][0].keys).toEqual([
      { key: "token", value: "glpat-test-token" },
      { key: "username", value: "deploy-user" },
    ])
  })

  it("replaces the existing secret's keys instead of creating a new one", async () => {
    const user = userEvent.setup()
    renderDialog(existingSecret)

    await user.click(screen.getByRole("button", { name: "Open" }))
    expect(
      screen.getByRole("heading", { name: "Replace git access token" })
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText("Token"), "glpat-rotated")
    await user.click(screen.getByRole("button", { name: "Replace token" }))

    await waitFor(() => expect(updateSecretById).toHaveBeenCalledTimes(1))
    expect(updateSecretById).toHaveBeenCalledWith({
      secretId: "secret-id-1",
      params: { keys: [{ key: "token", value: "glpat-rotated" }] },
    })
    expect(createSecret).not.toHaveBeenCalled()
  })

  it("does not submit without a token", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole("button", { name: "Open" }))
    await user.click(screen.getByRole("button", { name: "Add token" }))

    await waitFor(() =>
      expect(screen.getByText("Token is required")).toBeInTheDocument()
    )
    expect(createSecret).not.toHaveBeenCalled()
    expect(updateSecretById).not.toHaveBeenCalled()
  })
})
