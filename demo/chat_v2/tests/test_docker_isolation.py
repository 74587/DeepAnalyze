import tempfile
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend_app.services import docker_executor, workspace


class DockerIsolationTest(unittest.TestCase):
    def test_container_mounts_only_session_and_applies_resource_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                execution_mode="docker",
                workspace_base_dir=temp_dir,
                docker_image="deepanalyze-test:latest",
                docker_network_mode="none",
                docker_memory="512m",
                docker_cpus=0.5,
                docker_pids_limit=64,
                docker_user="1000:1000",
                docker_read_only=True,
                docker_tmpfs_size="64m",
            )
            commands = []

            def capture(args, **_kwargs):
                commands.append(args)
                return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            docker_executor._SESSION_CONTAINERS.clear()
            with (
                patch.object(docker_executor, "settings", safe_settings),
                patch.object(workspace, "settings", safe_settings),
                patch.object(docker_executor, "_container_is_running", return_value=False),
                patch.object(docker_executor, "_container_exists", return_value=False),
                patch.object(docker_executor, "_image_exists", return_value=True),
                patch.object(docker_executor, "_run_docker_command", side_effect=capture),
            ):
                docker_executor.ensure_execution_backend_ready("session-1")

            run_args = commands[-1]
            mount_value = run_args[run_args.index("-v") + 1]
            expected_session_root = str(Path(temp_dir, "session-1").resolve())
            self.assertEqual(mount_value, f"{expected_session_root}:/workspace:rw")
            self.assertNotEqual(mount_value, f"{Path(temp_dir).resolve()}:/workspace:rw")
            for required in [
                "--cap-drop",
                "--security-opt",
                "--network",
                "--memory",
                "--cpus",
                "--pids-limit",
                "--read-only",
                "--tmpfs",
                "--user",
            ]:
                self.assertIn(required, run_args)

    def test_container_names_do_not_collide_after_sanitizing(self):
        first = docker_executor._container_name_for_session("session.a")
        second = docker_executor._container_name_for_session("session-a")
        self.assertNotEqual(first, second)

    def test_existing_container_must_match_labels_and_session_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_root = Path(temp_dir, "session-1").resolve()
            session_root.mkdir()
            inspect_payload = [{
                "Config": {"Labels": {
                    docker_executor.MANAGED_LABEL_KEY: "true",
                    docker_executor.SESSION_LABEL_KEY: "session-1",
                }},
                "Mounts": [{"Source": str(session_root), "Destination": "/workspace"}],
            }]
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": json.dumps(inspect_payload), "stderr": ""},
            )()
            with patch.object(docker_executor, "_run_docker_command", return_value=completed):
                self.assertTrue(docker_executor._container_matches_session(
                    "container", "session-1", session_root
                ))
                self.assertFalse(docker_executor._container_matches_session(
                    "container", "session-2", session_root
                ))


if __name__ == "__main__":
    unittest.main()
