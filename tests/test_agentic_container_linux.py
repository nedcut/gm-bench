"""Container isolation on a native Linux Docker Engine (no Docker Desktop host alias)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gm_bench.agentic import container


def _fake_docker(
    monkeypatch: pytest.MonkeyPatch, *, system: str, os_name: str, gateway: str = "172.17.0.1", options: str = ""
) -> list:
    calls: list[tuple[str, ...]] = []

    def fake(_docker: str, *args: str, **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if args[:1] == ("info",):
            return SimpleNamespace(returncode=0, stdout=f"{os_name}|{options}\n", stderr="")
        if args[:2] == ("network", "inspect"):
            return SimpleNamespace(returncode=0, stdout=f"{gateway} \n", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(container.platform, "system", lambda: system)
    monkeypatch.setattr(container, "_docker", fake)
    return calls


def test_native_linux_engine_listens_on_the_bridge_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, system="Linux", os_name="Ubuntu 24.04.4 LTS")

    gateway = container.host_gateway()
    image = {"image_id": "sha256:" + "d" * 64, "host_gateway": gateway}

    assert gateway == "172.17.0.1"
    assert container.driver_listen_host(image) == "172.17.0.1"
    assert container._host_args(image) == ("--add-host", "host.docker.internal:172.17.0.1")


@pytest.mark.parametrize(
    ("system", "os_name"),
    [("Linux", "Docker Desktop"), ("Darwin", "Docker Desktop"), ("Darwin", "Ubuntu 24.04 LTS"), ("Linux", "")],
)
def test_docker_desktop_and_other_hosts_keep_the_loopback(
    monkeypatch: pytest.MonkeyPatch, system: str, os_name: str
) -> None:
    calls = _fake_docker(monkeypatch, system=system, os_name=os_name)

    assert container.host_gateway() is None
    assert not any(call[:2] == ("network", "inspect") for call in calls)
    image = {"image_id": "sha256:" + "d" * 64}
    assert container.driver_listen_host(image) == "127.0.0.1"
    assert container._host_args(image) == ()


def test_harness_command_maps_the_host_alias_before_the_image(tmp_path: Path) -> None:
    image = {"image_id": "sha256:" + "d" * 64, "host_gateway": "172.17.0.1"}
    harness = container.ContainerHarness.__new__(container.ContainerHarness)
    harness.docker, harness.image, harness.scratch = "docker", image, tmp_path
    harness.volume, harness.token, harness.names, harness.driver_port = "gmb-home-x", "t", [], 4242

    argv, _name = harness.command(["opencode", "--version"])

    at = argv.index("--add-host")
    assert argv[at + 1] == "host.docker.internal:172.17.0.1"
    assert at < argv.index(image["image_id"])


def test_rootless_docker_is_refused_rather_than_listening_on_an_unreachable_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_docker(
        monkeypatch, system="Linux", os_name="Ubuntu 24.04.4 LTS", options="name=seccomp,profile=builtin name=rootless "
    )

    with pytest.raises(container.ContainerError, match="rootless"):
        container.host_gateway()
    assert not any(call[:2] == ("network", "inspect") for call in calls)
