"""Print the public key of each org's registry SSH key (`github-ssh-key` secret).

Tracecat stores only the private key and never displays the public half, but
git hosts need the public key registered as a (read-only) deploy key. Run this
inside the API container on the target deployment:

    docker exec -i <api-container> python3 - < scripts/print_registry_ssh_pubkey.py

Prints one line per organization; add the printed key to the git host
(GitHub/GitLab repo -> Settings -> Deploy keys). Read-only access is enough.
"""

import asyncio
import os
import subprocess
import tempfile


async def main() -> None:
    from sqlalchemy import text

    from tracecat.auth.types import Role
    from tracecat.db.engine import get_async_session_context_manager
    from tracecat.secrets.service import SecretsService

    async with get_async_session_context_manager() as session:
        orgs = (await session.execute(text("SELECT id, name FROM organization"))).all()
        for org_id, org_name in orgs:
            role = Role(
                type="service",
                service_id="tracecat-api",
                organization_id=str(org_id),
                access_level="admin",
                scopes=frozenset({"org:secret:read"}),
            )
            svc = SecretsService(session, role=role)
            try:
                priv = (await svc.get_ssh_key()).get_secret_value()
            except Exception as e:
                print(f"[{org_name}] no github-ssh-key ({type(e).__name__})")
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as f:
                f.write(priv)
                path = f.name
            os.chmod(path, 0o600)
            out = subprocess.run(
                ["ssh-keygen", "-y", "-f", path], capture_output=True, text=True
            )
            os.unlink(path)
            if out.returncode == 0:
                print(f"[{org_name}] PUBLIC KEY: {out.stdout.strip()}")
            else:
                print(f"[{org_name}] ssh-keygen failed: {out.stderr.strip()}")


if __name__ == "__main__":
    asyncio.run(main())
