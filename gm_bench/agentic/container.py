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
  through a bind mount, and presents a per-run secret on every connection;
- :data:`HOST_ALIAS` reaches every service on the host loopback, not only
  the driver, so each invocation starts as root in :data:`EGRESS_ENTRYPOINT`,
  which installs a firewall in the container's own network namespace
  (:data:`EGRESS_POLICY`) and then drops to the unprivileged ``node`` user
  with no capabilities before the harness starts. Before each episode
  :func:`container_egress_problems` proves the rule holds: a canary
  listener on the host loopback must be unreachable from the container.

The free ``opencode/*`` models need no credentials, so none are provisioned.

The image is built locally from :func:`dockerfile`: a digest-pinned Node base,
Debian's ``python3`` for the standard-library proxy, ``procps``, and the
pinned ``opencode-ai`` package. The run records the image id (the content
digest of what actually ran), the Dockerfile's SHA-256, and the OpenCode
version the image reports.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import subprocess
from pathlib import Path
from typing import Any

CONTAINER_OPENCODE_VERSION = "1.18.31"
BASE_IMAGE = "node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9"
IMAGE_REPOSITORY = "gm-bench-agentic-opencode"
WORKDIR = "/work"
HOME = "/home/node"
HOST_ALIAS = "host.docker.internal"
# How long one ``docker rm`` / ``docker volume rm`` may take during cleanup.
CLEANUP_TIMEOUT_SECONDS = 60.0
EGRESS_ENTRYPOINT = "/usr/local/bin/gmb-egress"
EGRESS_POLICY = (
    "public internet only: private, loopback, link-local and host-gateway addresses rejected, "
    "except DNS to the container's resolvers and the driver's port on the host gateway; no IPv6 beyond loopback"
)
# Installed as root in the container's own network namespace, then every
# privilege is dropped: the harness runs as ``node`` with an empty capability
# bounding set under no-new-privileges, so it cannot change the rules. Any
# failure exits before the harness starts.
EGRESS_SCRIPT = r"""#!/bin/sh
set -eu
port="$1"
shift
case "$port" in ''|*[!0-9]*) echo "gmb-egress: bad driver port" >&2; exit 97 ;; esac
host=$(getent ahostsv4 host.docker.internal | awk 'NR==1 {print $1}')
[ -n "$host" ] || { echo "gmb-egress: cannot resolve host.docker.internal" >&2; exit 97; }
gateway=$(getent ahostsv4 gateway.docker.internal | awk 'NR==1 {print $1}') || true
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -d "$host" -p tcp --dport "$port" -j ACCEPT
for ns in $(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf); do
  case "$ns" in *:*) continue ;; esac
  iptables -A OUTPUT -d "$ns" -p udp --dport 53 -j ACCEPT
  iptables -A OUTPUT -d "$ns" -p tcp --dport 53 -j ACCEPT
done
for net in "$host" ${gateway:+"$gateway"} 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
    172.16.0.0/12 192.168.0.0/16 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4; do
  iptables -A OUTPUT -d "$net" -j REJECT
done
if [ -e /proc/net/if_inet6 ]; then
  ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -A OUTPUT -j REJECT
fi
exec setpriv --reuid=node --regid=node --init-groups --inh-caps=-all --bounding-set=-all \
  env HOME=/home/node USER=node LOGNAME=node "$@"
"""


class ContainerError(RuntimeError):
    """Docker is missing, the image would not build, or it is not what was pinned."""


def dockerfile(opencode_version: str = CONTAINER_OPENCODE_VERSION) -> str:
    return (
        f"FROM {BASE_IMAGE}\n"
        "RUN apt-get update \\\n"
        " && apt-get install -y --no-install-recommends python3 procps ca-certificates iptables \\\n"
        " && rm -rf /var/lib/apt/lists/*\n"
        f"RUN npm install -g opencode-ai@{opencode_version} && npm cache clean --force\n"
        f"COPY --chmod=755 <<'GMB_EGRESS' {EGRESS_ENTRYPOINT}\n{EGRESS_SCRIPT}GMB_EGRESS\n"
        "USER node\n"
        f"WORKDIR {WORKDIR}\n"
    )


def _docker(docker: str, *args: str, env: dict[str, str] | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([docker, *args], capture_output=True, text=True, check=False, env=env, **kwargs)
    except OSError as exc:
        raise ContainerError(f"cannot run {docker}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ContainerError(f"{docker} {args[0] if args else ''} did not finish within {exc.timeout} s") from exc


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
        "egress": EGRESS_POLICY,
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


# Every harness invocation and the egress probe start as root only long
# enough for EGRESS_ENTRYPOINT to install its rules; these are the only
# capabilities it keeps, and it drops them all before the harness runs.
_HARDENING = (
    "--init",
    "--user",
    "0:0",
    "--cap-drop",
    "ALL",
    "--cap-add",
    "NET_ADMIN",
    "--cap-add",
    "SETUID",
    "--cap-add",
    "SETGID",
    "--cap-add",
    "SETPCAP",
    "--security-opt",
    "no-new-privileges",
)

_EGRESS_PROBE = """
import json, os, socket, sys
def reachable(host, port):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return True
    except OSError:
        return False
status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
print(json.dumps({
    "uid": os.getuid(),
    "cap_eff": status["CapEff"].strip(),
    "cap_bnd": status["CapBnd"].strip(),
    "canary_reachable": reachable(sys.argv[1], int(sys.argv[2])),
}))
"""


def container_egress_problems(
    image: dict[str, Any], driver_port: int, *, docker: str = "docker", env: dict[str, str] | None = None
) -> list[str]:
    """Prove the egress rule on this Docker: a host-loopback canary must be unreachable from the harness.

    Runs :data:`EGRESS_ENTRYPOINT` exactly as a harness invocation does, then
    a probe that dials a listener the driver opened on the host loopback
    (standing in for every other local service) and reports its own uid and
    capabilities. Returns the problems found; empty means the rule held.
    """
    canary = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        canary.bind(("127.0.0.1", 0))
        canary.listen(4)
        port = canary.getsockname()[1]
        probe = _docker(
            docker,
            "run",
            "--rm",
            *_HARDENING,
            image["image_id"],
            EGRESS_ENTRYPOINT,
            str(driver_port),
            "python3",
            "-c",
            _EGRESS_PROBE,
            HOST_ALIAS,
            str(port),
            env=env,
            timeout=120,
        )
    finally:
        canary.close()
    if probe.returncode != 0:
        return [f"container egress probe failed: {(probe.stderr or probe.stdout).strip()[-400:]}"]
    try:
        report = json.loads(probe.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return [f"container egress probe printed no report: {probe.stdout.strip()[-400:]}"]
    problems = []
    if report.get("canary_reachable") is not False:
        problems.append("the container reached a host loopback listener other than the driver's port")
    if report.get("uid") == 0:
        problems.append("the harness would run as root in the container")
    if any(_capabilities_set(report.get(key)) for key in ("cap_eff", "cap_bnd")):
        problems.append("the harness would keep Linux capabilities in the container")
    return problems


def _capabilities_set(mask: Any) -> bool:
    try:
        return int(str(mask), 16) != 0
    except ValueError:
        return True


class ContainerHarness:
    """One episode's containers.

    Every harness invocation (the first run and each nudge) is a fresh
    ``docker run --rm`` with the scratch directory bind-mounted at
    :data:`WORKDIR` and a per-episode volume as the harness's home. It starts
    in :data:`EGRESS_ENTRYPOINT`, which allows the driver's ``driver_port``
    on the host gateway and nothing else there. Names are random, so nothing
    on the host command line names the seed.

    ``kill`` and ``close`` never raise: they run while an episode is being
    stopped or finalized, and a hung or failing ``docker`` must not lose the
    episode's result. What they could not remove is kept in ``problems``.
    """

    def __init__(
        self,
        image: dict[str, Any],
        scratch: Path,
        *,
        driver_port: int,
        docker: str = "docker",
        env: dict[str, str],
    ) -> None:
        self.image = image
        self.scratch = scratch
        self.driver_port = driver_port
        self.docker = docker
        self.env = env
        self.token = secrets.token_hex(6)
        self.volume = f"gmb-home-{self.token}"
        self.names: list[str] = []
        self.problems: list[str] = []
        created = _docker(docker, "volume", "create", self.volume, env=env, timeout=60)
        if created.returncode != 0:
            raise ContainerError(f"cannot create volume: {created.stderr.strip()[-400:]}")

    def command(self, harness_argv: list[str]) -> tuple[list[str], str]:
        name = f"gmb-{self.token}-{len(self.names) + 1}"
        self.names.append(name)
        argv = [
            self.docker,
            "run",
            "--rm",
            "--name",
            name,
            *_HARDENING,
            "--mount",
            f"type=bind,source={self.scratch},target={WORKDIR}",
            "--mount",
            f"type=volume,source={self.volume},target={HOME}",
            "--workdir",
            WORKDIR,
            self.image["image_id"],
            EGRESS_ENTRYPOINT,
            str(self.driver_port),
            *harness_argv,
        ]
        return argv, name

    def kill(self, name: str) -> None:
        """Stop a container whose ``docker run`` client was killed; the client going away does not stop it."""
        self._quietly("rm", "--force", name)

    def close(self) -> list[str]:
        """Remove every container and the home volume, each attempted; returns what could not be removed."""
        for name in self.names:
            self.kill(name)
        self._quietly("volume", "rm", "--force", self.volume)
        return list(self.problems)

    def _quietly(self, *args: str) -> None:
        try:
            done = _docker(self.docker, *args, env=self.env, timeout=CLEANUP_TIMEOUT_SECONDS)
        except ContainerError as exc:
            self.problems.append(f"docker {' '.join(args)}: {exc}")
            return
        gone = ("No such", "already in progress")
        if done.returncode != 0 and not any(marker in (done.stderr or "") for marker in gone):
            self.problems.append(f"docker {' '.join(args)}: {(done.stderr or done.stdout).strip()[-200:]}")
