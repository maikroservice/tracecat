import { z } from "zod"

export const GIT_SSH_URL_REGEX =
  /^git\+ssh:\/\/git@(?<hostname>[^/:]+)(?::(?<port>\d+))?\/(?<path>[^/@]+(?:\/[^/@]+)+)(?:\.git)?(?:@(?<ref>[^/@]+))?$/

export const GIT_HTTPS_URL_REGEX =
  /^https:\/\/(?<hostname>[^/:]+)(?::(?<port>\d+))?\/(?<path>[^/@]+(?:\/[^/@]+)+)(?:\.git)?(?:@(?<ref>[^/@]+))?$/

// Mirrors the backend validation in tracecat/git/constants.py but enforces at least
// an <org>/<repo> path structure on the client.

export function validateGitSshUrl(
  url: string | null | undefined,
  ctx: z.RefinementCtx
) {
  if (!url) return

  if (GIT_SSH_URL_REGEX.test(url)) return

  if (!url.startsWith("git+ssh://")) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "URL must start with 'git+ssh://' protocol",
    })
    return
  }

  if (!url.includes("git@")) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "URL must include 'git@' user specification",
    })
    return
  }

  const afterProtocol = url.replace("git+ssh://git@", "")
  const firstSlashIndex = afterProtocol.indexOf("/")

  if (firstSlashIndex === -1) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "URL must include a repository path",
    })
    return
  }

  const hostname = afterProtocol.substring(0, firstSlashIndex)
  const repoPath = afterProtocol.substring(firstSlashIndex + 1)

  if (!hostname) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Missing hostname",
    })
    return
  }

  if (hostname.includes(":")) {
    const colonIndex = hostname.lastIndexOf(":")
    const portPart = hostname.substring(colonIndex + 1)

    if (!portPart) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Missing port number after ':'",
      })
      return
    }

    if (!/^\d+$/.test(portPart)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Port must be numeric",
      })
      return
    }
  }

  const pathSegments = repoPath
    .split("/")
    .filter((segment) => segment.length > 0)

  if (pathSegments.length < 2) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Repository path must have at least 2 segments (e.g., org/repo)",
    })
    return
  }

  ctx.addIssue({
    code: z.ZodIssueCode.custom,
    message:
      "Must be a valid Git SSH URL (e.g., git+ssh://git@github.com/org/repo.git)",
  })
}

/**
 * Validates a GitLab repository URL.
 * Accepts both git+ssh:// and https:// schemes.
 */
export function validateGitLabUrl(
  url: string | null | undefined,
  ctx: z.RefinementCtx
) {
  if (!url) return

  // Check if it matches SSH or HTTPS format
  if (GIT_SSH_URL_REGEX.test(url) || GIT_HTTPS_URL_REGEX.test(url)) return

  const isHttps = url.startsWith("https://")
  const isSsh = url.startsWith("git+ssh://")

  if (!isHttps && !isSsh) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "URL must start with 'https://' or 'git+ssh://' protocol",
    })
    return
  }

  if (isSsh && !url.includes("git@")) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "SSH URL must include 'git@' user specification",
    })
    return
  }

  // Extract the part after the protocol
  const afterProtocol = isSsh
    ? url.replace("git+ssh://git@", "")
    : url.replace("https://", "")

  const firstSlashIndex = afterProtocol.indexOf("/")

  if (firstSlashIndex === -1) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "URL must include a repository path",
    })
    return
  }

  const hostname = afterProtocol.substring(0, firstSlashIndex)
  const repoPath = afterProtocol.substring(firstSlashIndex + 1)

  if (!hostname) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Missing hostname",
    })
    return
  }

  if (hostname.includes(":")) {
    const colonIndex = hostname.lastIndexOf(":")
    const portPart = hostname.substring(colonIndex + 1)

    if (!portPart) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Missing port number after ':'",
      })
      return
    }

    if (!/^\d+$/.test(portPart)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Port must be numeric",
      })
      return
    }
  }

  const pathSegments = repoPath
    .split("/")
    .filter((segment) => segment.length > 0)

  if (pathSegments.length < 2) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Repository path must have at least 2 segments (e.g., org/repo)",
    })
    return
  }

  ctx.addIssue({
    code: z.ZodIssueCode.custom,
    message:
      "Must be a valid Git URL (e.g., https://gitlab.com/org/repo.git or git+ssh://git@gitlab.com/org/repo.git)",
  })
}
