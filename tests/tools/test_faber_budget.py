"""Tiny real Windows Job probes and mocked Linux cgroup discovery tests."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


CI_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ci"
sys.path.insert(0, str(CI_SCRIPTS))
import resource_budget as budget


class CgroupDiscoveryTests(unittest.TestCase):
    def query(self, membership, mountinfo, files):
        texts = {"/proc/self/cgroup": membership, "/proc/self/mountinfo": mountinfo, **files}
        def read(path):
            try:
                return texts[path.as_posix()]
            except KeyError:
                raise FileNotFoundError(path)
        with mock.patch.object(budget, "_read_text", side_effect=read):
            return budget._linux_memory_limit_bytes()

    def test_systemd_service_limit_is_used_instead_of_unbounded_mount_root(self):
        limit = self.query("0::/system.slice/faber.service\n",
                           "25 20 0:25 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n", {
            "/sys/fs/cgroup/memory.max": "max",
            "/sys/fs/cgroup/system.slice/memory.max": "max",
            "/sys/fs/cgroup/system.slice/faber.service/memory.max": str(1024**3),
        })
        self.assertEqual(limit, 1024**3)

    def test_nested_groups_inherit_a_stricter_ancestor_limit(self):
        limit = self.query("0::/system.slice/faber.service/worker\n",
                           "25 20 0:25 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n", {
            "/sys/fs/cgroup/system.slice/faber.service/worker/memory.max": str(2*1024**3),
            "/sys/fs/cgroup/system.slice/faber.service/memory.max": str(256*1024**2),
        })
        self.assertEqual(limit, 256*1024**2)

    def test_v1_memory_controller_and_nonroot_mount_are_resolved(self):
        limit = self.query("4:cpu:/other\n5:memory:/parent/worker\n",
                           "25 20 0:25 /parent /sys/fs/cgroup/memory rw - cgroup cgroup rw,memory\n", {
            "/sys/fs/cgroup/memory/worker/memory.limit_in_bytes": str(128*1024**2),
            "/sys/fs/cgroup/memory/memory.limit_in_bytes": str(9223372036854771712),
        })
        self.assertEqual(limit, 128*1024**2)

    def test_v1_ancestor_limit_requires_hierarchical_accounting(self):
        membership = "5:memory:/parent/worker\n"
        mount = "25 20 0:25 / /sys/fs/cgroup/memory rw - cgroup cgroup rw,memory\n"
        files = {"/sys/fs/cgroup/memory/parent/memory.limit_in_bytes": str(128*1024**2)}
        self.assertIsNone(self.query(membership, mount, files))
        files["/sys/fs/cgroup/memory/parent/memory.use_hierarchy"] = "1"
        self.assertEqual(self.query(membership, mount, files), 128*1024**2)

    def test_missing_unbounded_or_unrelated_groups_are_not_a_guard(self):
        mount = "25 20 0:25 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
        self.assertIsNone(self.query("0::/service\n", mount, {}))
        self.assertIsNone(self.query("0::/service\n", mount, {"/sys/fs/cgroup/service/memory.max":"max"}))
        self.assertIsNone(self.query("0::/other\n", mount.replace(" / /sys", " /parent /sys"), {
            "/sys/fs/cgroup/memory.max": str(64*1024**2),
        }))

    def test_inherited_guard_must_be_real_and_small_enough(self):
        for cap in (None, 1025):
            with self.subTest(cap=cap), mock.patch.object(budget, "current_memory_limit_mb", return_value=cap):
                with self.assertRaises(budget.BudgetSetupError):
                    budget.ensure_guarded(1024)
        with mock.patch.object(budget, "current_memory_limit_mb", return_value=128):
            self.assertEqual(budget.ensure_guarded(1024), 128)

    def test_unguarded_linux_setup_never_starts_the_supplied_command(self):
        with mock.patch.object(budget, "current_memory_limit_mb", return_value=None), mock.patch.object(budget.subprocess, "Popen") as spawn:
            with self.assertRaises(budget.BudgetSetupError):
                budget._run_linux([sys.executable, "-c", "raise SystemExit(77)"], Path.cwd(), time.monotonic()+1, 128, None)
            spawn.assert_not_called()

    def test_hard_ceiling_and_argument_validation_precede_process_creation(self):
        for changes in ({"timeout_seconds":181}, {"timeout_seconds":float("nan")},
                        {"memory_mb":1025}, {"memory_mb":True}, {"command":"python -c pass"}):
            params = dict(command=[sys.executable, "-c", "pass"], cwd=Path.cwd())
            params.update(changes)
            with self.subTest(changes=changes), mock.patch.object(budget.subprocess, "Popen") as spawn:
                with self.assertRaises(ValueError):
                    budget.run_bounded(**params)
                spawn.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Real Job Object probes require Windows")
class WindowsJobTests(unittest.TestCase):
    def test_small_command_inherits_real_memory_guard_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix="faber-budget-") as directory:
            marker = Path(directory) / "guard.json"
            code = (f"import sys,json;sys.path.insert(0,{str(CI_SCRIPTS)!r});import resource_budget as b;"
                    "from pathlib import Path;"
                    "Path(sys.argv[1]).write_text(json.dumps([b.ensure_guarded(128),sys.argv[2]]))")
            result = budget.run_bounded([sys.executable, "-c", code, str(marker), "spaces & literal $(text)"], Path(directory), 5, 128)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.timed_out)
            self.assertEqual(json.loads(marker.read_text()), [128, "spaces & literal $(text)"])
            self.assertLessEqual(result.peak_memory_mb, 128)

    def test_nonzero_exit_is_preserved(self):
        result = budget.run_bounded([sys.executable, "-c", "raise SystemExit(7)"], Path.cwd(), 5, 128)
        self.assertEqual(result.returncode, 7)
        self.assertFalse(result.timed_out)

    def test_timeout_stops_owned_grandchild_heartbeat(self):
        with tempfile.TemporaryDirectory(prefix="faber-budget-") as directory:
            heartbeat = Path(directory) / "heartbeat.txt"
            grandchild = "import sys,time;from pathlib import Path\np=Path(sys.argv[1])\nwhile True:\n p.write_text(str(time.monotonic_ns()));time.sleep(.03)\n"
            code = ("import sys,subprocess,time;"
                    f"subprocess.Popen([sys.executable,'-c',{grandchild!r},sys.argv[1]]);time.sleep(10)")
            result = budget.run_bounded([sys.executable, "-c", code, str(heartbeat)], Path(directory), 1.2, 128)
            self.assertTrue(result.timed_out)
            self.assertEqual(result.returncode, 124)
            self.assertLess(result.elapsed_seconds, 4)
            self.assertTrue(heartbeat.exists(), "Grandchild must actually run before testing cleanup")
            stopped = heartbeat.read_text()
            time.sleep(.15)
            self.assertEqual(heartbeat.read_text(), stopped, "Timeout left a grandchild running")

    def test_allocation_is_refused_by_128_mib_aggregate_job_cap(self):
        with tempfile.TemporaryDirectory(prefix="faber-budget-") as directory:
            marker = Path(directory) / "allocation.json"
            # Even if the cap regresses, this probe attempts at most 128 MiB payload.
            code = """import json,sys
from pathlib import Path
chunks=[]
blocked=False
try:
    for _ in range(16):
        chunks.append(bytearray(8*1024*1024))
except MemoryError:
    blocked=True
allocated=len(chunks)*8
del chunks
Path(sys.argv[1]).write_text(json.dumps([blocked,allocated]))
"""
            result = budget.run_bounded([sys.executable, "-c", code, str(marker)], Path(directory), 5, 128)
            self.assertEqual(result.returncode, 0)
            blocked, allocated = json.loads(marker.read_text())
            self.assertTrue(blocked, "Kernel did not refuse the bounded memory probe")
            self.assertGreater(allocated, 0)
            self.assertLess(allocated, 128)
            self.assertEqual(result.memory_limit_mb, 128)
            # Native accounting can include the refused allocation attempt. Keep
            # its raw value; the inherited hard cap and actual refusal are tested.
            self.assertGreater(result.peak_memory_mb, 0)

    def test_failed_assignment_cannot_launch_supplied_command(self):
        with tempfile.TemporaryDirectory(prefix="faber-budget-") as directory:
            marker = Path(directory) / "must-not-run.txt"
            command = [sys.executable, "-c", "import sys;from pathlib import Path;Path(sys.argv[1]).write_text('started')", str(marker)]
            with mock.patch.object(budget._WindowsJob, "assign", side_effect=budget.BudgetSetupError("assignment unavailable")):
                with self.assertRaises(budget.BudgetSetupError):
                    budget.run_bounded(command, Path(directory), 5, 128)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
