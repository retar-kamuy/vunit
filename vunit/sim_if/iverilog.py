# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2015, 2016, Lars Asplund lars.anders.asplund@gmail.com

"""
Interface for the Icarus Verilog simulator
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

class IVerilogInterface(SimulatorInterface):
    """
    Interface for the Icarus Verilog simulator
    """

    name = "iverilog"
    package_users_depend_on_bodies = False

    compile_options = [
        ListOfStringOption("iverilog.iverilog_flags"),
    ]

    sim_options = [
        ListOfStringOption("iverilog.vvp_flags"),
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
        return cls.find_toolchain(['iverilog'])

    def __init__(self, prefix, output_path, gui=False):
        self._prefix = prefix
        self._libraries = []
        self._output_path = output_path
        self._source_files = []
        self._compile_options = []

    def setup_library_mapping(self, project):
        """
        Compile project using vhdl_standard
        """
        mapped_libraries = self._get_mapped_libraries()

        for library in project.get_libraries():
            self._libraries.append(library)
            self.create_library(library.name, library.directory, mapped_libraries)

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

        self._compile_options += source_file.compile_options.get('iverilog_flags', [])

        cmd = join(self._prefix, 'iverilog')
        args = []
        args += ['-E']
        args += ['-g2012'] # Enables the IEEE1800-2012 standard, which includes SystemVerilog
        args += ['-o', output_path]
        args += source_file.compile_options.get('iverilog_flags', [])
        for include_dir in source_file.include_dirs:
            args += ['-I', include_dir]
        for key, value in source_file.defines.items():
            args += ['-D', '%s=%s' % (key, value.replace('"','\\"'))]
        args += ['-I', os.path.dirname(source_file.name)]
        args += [source_file.name]

        argsfile = "%s/iverilog_compile_verilog_file_%s.args" % (self._output_path, source_file.library.name)
        write_file(argsfile, "\n".join(args) + "\n")
        return [cmd, *args]

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
        # cds = CDSFile.parse(self._cdslib)
        # return cds
        return None

    def elaborate(self, output_path, target_filename):
        """
        Elaborates with entity as top level using generics
        """
        cmd = join(self._prefix, 'iverilog')
        args = []
        args += ['-g2012'] # Enables the IEEE1800-2012 standard, which includes SystemVerilog
        args += ['-o', os.path.join(output_path, target_filename)]
        # args += ['-s', os.path.splitext(target_filename)[0]]
        args += self._compile_options
        args += self._source_files

        argsfile = "%s/iverilog_elaborate_%s.args" % (self._output_path, target_filename)
        write_file(argsfile, "\n".join(args) + "\n")
        return [cmd, *args]
        # vvp_path = os.path.join(
        #     self._output_path,
        #     "libraries",
        # vcsargs = []
        # write_file(dofile, "\n".join(docmds))
        # return run_command([cmd, *vcsargs], cwd=output_path)

    def simulate(self, output_path, test_suite_name, config, elaborate_only=False):
        """
        Simulates with entity as top level using generics
        """
        LEGAL_CHARS = string.printable
        ILLEGAL_CHARS = ' <>"|:*%?\\/#&;()'
        test_name = (
            "".join(char if (char in LEGAL_CHARS) and (char not in ILLEGAL_CHARS) else "_" for char in test_suite_name) + "_"
        )
        print("test = ", test_name)

        vvp_path = '%s/elab/%s' % (os.path.dirname(output_path), test_name) 

        simv_exec = '%s/simv' % (vvp_path) 
        simv_incr = '%s/dir' % (vvp_path) 
        print("SIMV=", vvp_path)
        if not os.path.isfile(simv_exec):
          if not os.path.exists(vvp_path):
              os.makedirs(vvp_path)
              os.makedirs(simv_incr)
        cmd = [join(self._prefix, 'vcs')]
        cmd += ['-g2012']
        cmd += ['-s']
        cmd += ['%s' % join('%s.%s' % (config.library_name, config.entity_name))]

        cmd += "\n".join(generics)

        print("ELAB CMD", cmd)
        if not run_command(cmd, cwd=vvp_path):
          return False

        print("SIM CMD", cmd)
        if not elaborate_only:
            #if not run_command(["ls", 'exitstatus', 
            #                         simvlogfile],
            #          cwd=output_path):
            #    return False
            if not run_command(cmd, cwd=output_path):
                return False
        return True

    @staticmethod
    def _generic_args(entity_name, generics):
        """
        Create Icarus Verilog arguments for generics and parameters
        """
        args = ['+%s' % entity_name]
        return args
