/**
 * @jest-environment jsdom
 */

import { render, screen } from "@testing-library/react"
import React from "react"

import { WorkflowSaveActions } from "@/components/nav/builder-nav"

// ── Next.js internals ──────────────────────────────────────────────────────
jest.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode
    href: string
  }) => React.createElement("a", { href }, children),
}))

jest.mock("next/navigation", () => ({
  usePathname: jest.fn(() => "/"),
  useRouter: jest.fn(() => ({ push: jest.fn() })),
}))

// ── TanStack Query ─────────────────────────────────────────────────────────
jest.mock("@tanstack/react-query", () => ({
  useIsMutating: jest.fn(() => 0),
}))

// ── Providers ──────────────────────────────────────────────────────────────
jest.mock("@/providers/workflow", () => ({
  useWorkflow: jest.fn(() => ({ workflow: null, workflowId: "test-wf-id" })),
}))

jest.mock("@/providers/workspace-id", () => ({
  useWorkspaceId: jest.fn(() => "test-workspace-id"),
}))

jest.mock("@/providers/builder", () => ({
  useWorkflowBuilder: jest.fn(() => ({})),
}))

// ── Hooks ──────────────────────────────────────────────────────────────────
jest.mock("@/hooks/use-workspace", () => ({
  useWorkspaceDetails: jest.fn(() => ({
    workspace: null,
    workspaceLoading: false,
  })),
}))

jest.mock("@/hooks/use-feature-flags", () => ({
  useFeatureFlag: jest.fn(() => ({ isFeatureEnabled: () => false })),
}))

const mockUseGitLabCredentialsStatus = jest.fn()

jest.mock("@/lib/hooks", () => ({
  useGitLabCredentialsStatus: (...args: unknown[]) =>
    mockUseGitLabCredentialsStatus(...args),
  useOrgAppSettings: jest.fn(() => ({ appSettings: null })),
  useWorkflowManager: jest.fn(() => ({})),
  useCreateDraftWorkflowExecution: jest.fn(() => ({})),
}))

// ── Heavy UI components not under test ────────────────────────────────────
jest.mock("@/components/editor/codemirror/code-editor", () => ({
  CodeEditor: () => null,
}))

jest.mock("@/components/export-workflow-dropdown-item", () => ({
  ExportMenuItem: () => null,
}))

jest.mock("@/components/loading/spinner", () => ({
  Spinner: () => React.createElement("div", { "data-testid": "spinner" }),
}))

jest.mock("@/components/validation-errors", () => ({
  ValidationErrorView: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}))

jest.mock("@/lib/utils", () => ({
  cn: (...classes: (string | undefined)[]) => classes.filter(Boolean).join(" "),
  copyToClipboard: jest.fn(),
}))

// ── Helpers ────────────────────────────────────────────────────────────────

const defaultProps = {
  workflow: { version: 1 },
  validationErrors: null,
  onSave: jest.fn().mockResolvedValue(undefined),
  onPublish: jest.fn().mockResolvedValue(undefined),
}

function renderSaveActions(credentialsStatus: { exists: boolean } | undefined) {
  mockUseGitLabCredentialsStatus.mockReturnValue({
    credentialsStatus,
    credentialsStatusIsLoading: false,
    credentialsStatusError: null,
    refetchCredentialsStatus: jest.fn(),
  })
  return render(<WorkflowSaveActions {...defaultProps} />)
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("WorkflowSaveActions git publish dropdown (triangle button)", () => {
  it("shows the dropdown trigger when GitLab credentials exist", () => {
    renderSaveActions({ exists: true })
    expect(
      screen.getByTestId("git-publish-dropdown-trigger")
    ).toBeInTheDocument()
  })

  it("hides the dropdown trigger when GitLab credentials do not exist", () => {
    renderSaveActions({ exists: false })
    expect(
      screen.queryByTestId("git-publish-dropdown-trigger")
    ).not.toBeInTheDocument()
  })

  it("hides the dropdown trigger when credentials status is undefined (e.g. 403 for editors before fix)", () => {
    renderSaveActions(undefined)
    expect(
      screen.queryByTestId("git-publish-dropdown-trigger")
    ).not.toBeInTheDocument()
  })
})
