"""Negative controls for the fixed-purpose M1 child process admission."""
import ast
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch


class M1ChildGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        control = Path(__file__).resolve().parents[1]
        tree = ast.parse((control/'guard.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in {'writable', 'audit'}]
        self.scope = dict(Path=Path, os=os, shlex=shlex, sys=sys, OUT=self.root,
                          VENDOR=self.root/'vendor', CONTROL=control, MODE='pytest',
                          denied=[], media_calls=[])
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(control/'guard.py'), 'exec'), self.scope)
        self.command = [sys.executable, str(control/'guard.py'), 'm1-current',
                        str(self.root/'authority.sqlite'), str(self.root/'retained.anchor'), 'book01_p03']
        self.environment = patch.dict(os.environ, FFMPEG_PATH=str(self.root/'ffmpeg'),
                                       FFPROBE_PATH=str(self.root/'ffprobe'))
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def admit(self, command):
        self.scope['audit']('subprocess.Popen', (sys.executable, command, None, {}))

    def test_fixed_reader_is_admitted(self):
        self.admit(self.command)

    def test_arbitrary_python_code_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.admit([sys.executable, '-c', 'print(1)'])

    def test_other_mode_is_rejected(self):
        self.command[2] = 'server'
        with self.assertRaises(PermissionError):
            self.admit(self.command)

    def test_database_outside_workspace_is_rejected(self):
        self.command[3] = str(self.root.parent/'authority.sqlite')
        with self.assertRaises(PermissionError):
            self.admit(self.command)

    def test_extra_argument_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.admit(self.command+['unexpected'])

    def test_external_network_is_rejected_in_child_mode(self):
        self.scope['MODE'] = 'm1-current'
        with self.assertRaises(PermissionError):
            self.scope['audit']('socket.connect', (None, ('203.0.113.1', 443)))


if __name__ == '__main__':
    unittest.main()
