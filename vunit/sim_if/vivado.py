# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2014-2023, Lars Asplund lars.anders.asplund@gmail.com

"""
Interface for the Vivado simulator
"""

from __future__ import print_function
import os
from os import makedirs
import shutil
from os.path import join, dirname, abspath, relpath
import subprocess
import sys
import string
import logging
import pathlib
from vunit.ostools import write_file, file_exists
from vunit.hashing import hash_string
from . import (SimulatorInterface,
                                       ListOfStringOption,
                                       run_command,
)
#from vunit.simulator_interface import (SimulatorInterface,
#                                       ListOfStringOption,
#                                       run_command,
#)
from vunit.exceptions import CompileError

LOGGER = logging.getLogger(__name__)

class VivadoInterface(SimulatorInterface):
    """
    Interface for the Vivado simulator
    """

    name = "vivado"
    package_users_depend_on_bodies = False

    compile_options = [
        ListOfStringOption("vivado.xvlog_flags"),
    ]

    sim_options = [
        ListOfStringOption("vivado.xsim_flags"),
    ]

    @classmethod
    def from_args(cls, args, output_path, **kwargs):
        """
        Create new instance from command line arguments object
        """
        persistent = not (args.unique_sim or args.gui)

        return cls(
            prefix=cls.find_prefix(),
            output_path=output_path,
            gui=args.gui,
        )

    @classmethod
    def find_prefix_from_path(cls):
        """
        Find Icarus Verilog simulator from PATH environment variable
        """
        return cls.find_toolchain(['vivado'])

    def __init__(self, prefix, output_path, gui=False):
        self._prefix = prefix
        self._libraries = {}
        self._output_path = output_path
        self._gui = gui
        self._source_files = []

    def setup_library_mapping(self, project):
        """
        Compile project using vhdl_standard
        """
        # mapped_libraries = self._get_mapped_libraries()

        # for library in project.get_libraries():
        #     self._libraries.append(library)
        #     self.create_library(library.name, library.directory, mapped_libraries)

    def compile_source_file_command(self, source_file):
        """
        Returns the command to compile a single source file
        """
        if source_file.is_any_verilog:
            return self.compile_verilog_file_command(source_file)

        LOGGER.error("Unknown file type: %s", source_file.file_type)
        raise CompileError

    def compile_verilog_file_command(self, source_file):
        """
        Returns commands to compile a Verilog file
        """
        preprocessed_path = os.path.join(pathlib.Path(self._output_path).parent, "preprocessed")
        prefix = hash_string(str(pathlib.Path(source_file.name).parent))
        output_dir = os.path.join(preprocessed_path, prefix)
        if not file_exists(output_dir):
            os.makedirs(output_dir)
        output_path = os.path.join(output_dir, os.path.basename(source_file.name))
        self._source_files.append(output_path)

        self._libraries[os.path.splitext(os.path.basename(source_file.name))[0]] = source_file.library.name

        cmd = join(self._prefix, 'xvlog')
        args = []
        args += ['-sv']
        # args += ['-work', '%s=%s' % (source_file.library.name, os.path.join(self._output_path, 'libraries', source_file.library.name))]
        args += ['-work', '%s=%s' % (source_file.library.name, os.path.join(self._output_path, 'libraries', source_file.library.name))]
        args += source_file.compile_options.get('xvlog_flags', [])
        for include_dir in source_file.include_dirs:
            args += ['-i', include_dir]
        for key, value in source_file.defines.items():
            args += ['-d', '%s=%s' % (key, value.replace('"','\\"'))]
        args += ['-i', os.path.dirname(source_file.name)]
        args += [source_file.name]
        args += ['-log', os.path.join(self._output_path, 'xvlog_%s.log' % os.path.splitext(os.path.basename(source_file.name))[0])]

        argsfile = "%s/xvlog_%s.args" % (self._output_path, source_file.library.name)
        write_file(argsfile, "\n".join(args))
        # return [cmd, *args]
        return [cmd, '-f', argsfile]

    def create_library(self, library_name, library_path, mapped_libraries=None):
        """
        Create and map a library_name to library_path
        """
        mapped_libraries = mapped_libraries if mapped_libraries is not None else {}

        if not file_exists(abspath(library_path)):
            os.makedirs(abspath(library_path))

        if library_name in mapped_libraries and mapped_libraries[library_name] == library_path:
            return

    def _get_mapped_libraries(self):
        """
        Get mapped libraries from cds.lib file
        """
        libraries_path = pathlib.Path('vunit_out/vivado/libraries')
        vivado = os.listdir(path='vunit_out/vivado/libraries')
        return vivado

    def elaborate(self, output_path, target_filename):
        """
        Elaborates with entity as top level using generics
        """
        cmd = join(self._prefix, 'xelab')
        args = []
        for library_dir in self._get_mapped_libraries():
            args += ['-L', '%s=%s' % (library_dir, os.path.join(self._output_path, 'libraries', library_dir))]
        args += ['%s.%s' % (self._libraries[os.path.splitext(target_filename)[0]], os.path.splitext(target_filename)[0])]
        args += ['-log', os.path.join(self._output_path, 'xelab_%s.log' % os.path.splitext(target_filename)[0])]

        argsfile = '%s/xelab_%s.args' % (self._output_path, os.path.splitext(target_filename)[0])
        write_file(argsfile,'\n'.join(args) + '\n')
        return run_command([cmd, '-f', argsfile], cwd=self._output_path)

    def simulate(self, output_path, test_suite_name, config, elaborate_only=False):
        """
        Simulates with entity as top level using generics
        """
        launch_gui = self._gui is not False

        testplusarg = {
            'enabled_test_cases': test_suite_name.split('.')[-1],
            'output_path': '%s/' % output_path
        }

        cmd = join(self._prefix, 'xsim')
        args = []
        if launch_gui:
            args += ['-gui']
        args += ['-runall']
        args += ['-testplusarg', '"enabled_test_cases=%s"' % testplusarg['enabled_test_cases']]
        args += ['-testplusarg', '"output_path=%s"' % testplusarg['output_path']]
        args += ['%s.%s' % (config.library_name, config.entity_name)]
        args += ['-log', os.path.join(output_path, 'xsim.log')]

        argsfile = '%s/xsim_%s.args' % (output_path, test_suite_name)
        write_file(argsfile,'\n'.join(args) + '\n')
        return run_command([cmd, '-file', argsfile], cwd=self._output_path)
