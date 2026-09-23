"""Run the OpenCode harness in a Docker container (``gm-bench agentic --isolation container``).

On a same-user machine the agent's shell can run ``ps``, see the driver's
command line (``--seeds``), and follow it to the run directory and the
checkout (docs/bench_v2_spec.md, sandbox section). Here the harness runs in a
container instead, and the engine, the seed, and the ledger stay in the
driver process on the host:

- the container has its own process namespace, so ``ps`` shows only the
  harness and what it started;
- the only host path mounted is the episode's scratch directory (the proxy,
  its secret, and ``opencode.json``), at :data:`WORKDIR`;
- the harness's home is a per-episode Docker volume, so OpenCode's session
  store survives from one invocation to the next (nudges resume with
  ``--session``) and is deleted with the episode; nothing carries over to the
  next episode, and no host configuration (``~/.config/opencode``, auth,
  AGENTS.md, skills) is visible;
- the proxy reaches the driver over TCP on the host loopback through
  :data:`HOST_ALIAS`, because Docker Desktop cannot pass a host Unix socket
  through a bind mount, and presents a per-run secret on every connection.

The free ``opencode/*`` models need no credentials, so none are provisioned.

The image is built locally from :func:`dockerfile`: a digest-pinned Node base,
Debian's ``python3`` for the standard-library proxy, ``procps``, and the
pinned ``opencode-ai`` package. The run records the image id (the content
digest of what actually ran), the Dockerfile's SHA-256, and the OpenCode
version the image reports.
"""

from __future__ import annotations

import hashlib
import secrets
import subprocess
from pathlib import Path
from typing import Any

CONTAINER_OPENCODE_VERSION = "1.18.31"
BASE_IMAGE = "node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9"
IMAGE_REPOSITORY = "gm-bench-agentic-opencode"
WORKDIR = "/work"
HOME = "/home/node"
HOST_ALIAS = "host.docker.internal"


class ContainerError(RuntimeError):
    """Docker is missing, the image would not build, or it is not what was pinned."""


def dockerfile(opencode_version: str = CONTAINER_OPENCODE_VERSION) -> str:
    return (
        f"FROM {BASE_IMAGE}\n"
        "RUN apt-get update \\\n"
        " && apt-get install -y --no-install-recommends python3 procps ca-certificates \\\n"
        " && rm -rf /var/lib/apt/lists/*\n"
        f"RUN npm install -g opencode-ai@{opencode_version} && npm cache clean --force\n"
        "USER node\n"
        f"WORKDIR {WORKDIR}\n"
    )


def _docker(docker: str, *args: str, env: dict[str, str] | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([docker, *args], capture_output=True, text=True, check=False, env=env, **kwargs)
    except OSError as exc:
        raise ContainerError(f"cannot run {docker}: {exc}") from exc


def ensure_image(
    opencode_version: str = CONTAINER_OPENCODE_VERSION, *, docker: str = "docker", env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Build the harness image if it is missing and describe exactly what will run."""
    text = dockerfile(opencode_version)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    tag = f"{IMAGE_REPOSITORY}:{opencode_version}-{digest[:12]}"
    server = _docker(docker, "version", "--format", "{{.Server.Version}}", env=env)
    if server.returncode != 0:
        raise ContainerError(f"docker daemon unavailable: {(server.stderr or server.stdout).strip()[-400:]}")
    inspect = _docker(docker, "image", "inspect", tag, "--format", "{{.Id}}", env=env)
    if inspect.returncode != 0:
        build = _docker(docker, "build", "--tag", tag, "-", input=text, env=env, timeout=1800)
        if build.returncode != 0:
            raise ContainerError(f"image build failed: {(build.stderr or build.stdout).strip()[-800:]}")
        inspect = _docker(docker, "image", "inspect", tag, "--format", "{{.Id}}", env=env)
    image_id = inspect.stdout.strip()
    if inspect.returncode != 0 or not image_id.startswith("sha256:"):
        raise ContainerError(f"cannot inspect {tag}: {inspect.stderr.strip()[-400:]}")
    probe = _docker(docker, "run", "--rm", "--network", "none", image_id, "opencode", "--version", env=env, timeout=120)
    reported = (probe.stdout or "").strip().splitlines()
    version = reported[-1].strip() if reported else None
    if version != opencode_version:
        raise ContainerError(f"image {tag} reports opencode {version!r}, pinned {opencode_version!r}")
    return {
        "runtime": "docker",
        "docker_server_version": server.stdout.strip(),
        "image": tag,
        "image_id": image_id,
        "base_image": BASE_IMAGE,
        "dockerfile_sha256": digest,
        "opencode_version": version,
        "workdir": WORKDIR,
    }


def container_sandbox_problems(
    image: dict[str, Any], *, docker: str = "docker", env: dict[str, str] | None = None
) -> list[str]:
    """The container-side half of the sandbox check: its python3 must not import gm_bench."""
    probe = _docker(
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        image["image_id"],
        "python3",
        "-c",
        "import gm_bench",
        env=env,
        timeout=120,
    )
    if probe.returncode == 0:
        return [f"python3 in {image['image']} can import gm_bench"]
    if "ModuleNotFoundError" not in probe.stderr:
        return [f"container sandbox probe did not run cleanly: {probe.stderr.strip()[-400:]}"]
    return []


class ContainerHarness:
    """One episode's containers.

    Every harness invocation (the first run and each nudge) is a fresh
    ``docker run --rm`` with the scratch directory bind-mounted at
    :data:`WORKDIR` and a per-episode volume as the harness's home. Names are
    random, so nothing on the host command line names the seed.
    """

    def __init__(self, image: dict[str, Any], scratch: Path, *, docker: str = "docker", env: dict[str, str]) -> None:
        self.image = image
        self.scratch = scratch
        self.docker = docker
        self.env = env
        self.token = secrets.token_hex(6)
        self.volume = f"gmb-home-{self.token}"
        self.names: list[str] = []
        created = _docker(docker, "volume", "create", self.volume, env=env)
        if created.returncode != 0:
            raise ContainerError(f"cannot create volume: {created.stderr.strip()[-400:]}")

    def command(self, harness_argv: list[str]) -> tuple[list[str], str]:
        name = f"gmb-{self.token}-{len(self.names) + 1}"
        self.names.append(name)
        argv = [
            self.docker,
            "run",
            "--rm",
            "--init",
            "--name",
            name,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,source={self.scratch},target={WORKDIR}",
            "--mount",
            f"type=volume,source={self.volume},target={HOME}",
            "--workdir",
            WORKDIR,
            self.image["image_id"],
            *harness_argv,
        ]
        return argv, name

    def kill(self, name: str) -> None:
        """Stop a container whose ``docker run`` client was killed; the client going away does not stop it."""
        _docker(self.docker, "rm", "--force", name, env=self.env, timeout=60)

    def close(self) -> None:
        for name in self.names:
            self.kill(name)
        _docker(self.docker, "volume", "rm", "--force", self.volume, env=self.env, timeout=60)
