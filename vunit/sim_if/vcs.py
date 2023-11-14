# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2014-2023, Lars Asplund lars.anders.asplund@gmail.com

"""
Interface for the Synopsys VCS simulator
"""

from __future__ import print_function
import os
import shutil
from os.path import join, dirname, abspath, relpath
import re
import sys
import string
import logging
from vunit.ostools import write_file, file_exists
from . import (SimulatorInterface,
                                       ListOfStringOption,
                                       run_command,
)
#from vunit.simulator_interface import (SimulatorInterface,
#                                       ListOfStringOption,
#                                       run_command,
#)
from vunit.exceptions import CompileError
from vunit.sim_if.vcs_setup_file import SetupFile
from ..vhdl_standard import VHDL

LOGGER = logging.getLogger(__name__)

class VCSInterface(SimulatorInterface):
    """
    Interface for the Synopsys VCS simulator
    """

    name = "vcs"
    supports_gui_flag = True
    package_users_depend_on_bodies = False

    compile_options = [
        ListOfStringOption("vcs.vhdl_flags"),
        ListOfStringOption("vcs.vlogan_flags"),
        ListOfStringOption("vcs.vcs_flags"),
    ]

    sim_options = [
        ListOfStringOption("vcs.vcs_sim_flags"),
    ]

    @staticmethod
    def add_arguments(parser):
        """
        Add command line arguments
        """
        group = parser.add_argument_group("Synopsys VCS",
                                          description="Synopsys VCS-specific flags")
        group.add_argument("--vcssetup",
                           default=None,
                           help="The synopsys_sim.setup file to use. If not given, VUnit maintains its own file.")

    @classmethod
    def from_args(cls, output_path, args):
        """
        Create new instance from command line arguments object
        """
        return cls(prefix=cls.find_prefix(),
                   output_path=output_path,
                   log_level=args.log_level,
                   gui=args.gui,
                   vcssetup=args.vcssetup)

    @classmethod
    def find_prefix_from_path(cls):
        """
        Find VCS simulator from PATH environment variable
        """
        return cls.find_toolchain(['vcs'])

    @staticmethod
    def supports_vhdl_2008_contexts():
        """
        Returns True when this simulator supports VHDL 2008 contexts
        """
        return False

    def __init__(self,  # pylint: disable=too-many-arguments
                 prefix, output_path, gui=False, log_level=None, vcssetup=None):
        self._prefix = prefix
        self._libraries = []
        self._output_path = output_path
        self._vhdl_standard = None
        self._gui = gui
        self._log_level = log_level
        if vcssetup is None:
            self._vcssetup = abspath('synopsys_sim.setup') ## FIXME: env var SYNOPSYS_SIM_SETUP is also possible
        else:
            self._vcssetup = abspath(vcssetup)
        try:
            _sim_setup = os.environ['SYNOPSYS_SIM_SETUP']
            LOGGER.debug("Environment variable SYNOPSYS_SIM_SETUP is '%s'" % _sim_setup)
            shutil.copy(_sim_setup, self._vcssetup)
        except KeyError:
            LOGGER.debug("Environment variable SYNOPSYS_SIM_SETUP is not set")

        LOGGER.debug("VCS Setup file is '%s'" % self._vcssetup)
        self._create_vcssetup()

    def _create_vcssetup(self):
        """
        Create the synopsys_sim.setup file in the output directory if it does not exist
        """
        contents = """\
-- synopsys_sim.setup: Defines the locations of compiled libraries.
-- NOTE: the library definitions in this file are handled by VUnit, other lines are kept intact
-- WORK > DEFAULT
-- DEFAULT : {0}/libraries/work
-- TIMEBASE = NS
""".format(self._output_path)

        if os.path.isfile(self._vcssetup):
            print("Reuse existing setup file: ", self._vcssetup)
        else:
            write_file(self._vcssetup, contents)

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
        if source_file.is_vhdl:
            return self.compile_vhdl_file_command(source_file)

        if source_file.is_any_verilog:
            return self.compile_verilog_file_command(source_file)

        LOGGER.error("Unknown file type: %s", source_file.file_type)
        raise CompileError

    @staticmethod
    def _vhdl_std_opt(vhdl_standard):
        """
        Convert standard to format of VCS command line flag
        """
        if vhdl_standard == VHDL.STD_2002:
            return "-vhdl08" # FIXME: no switch for 2002 in VCS
        elif vhdl_standard == VHDL.STD_2008:
            return "-vhdl08"
        elif vhdl_standard == VHDL.STD_2019:
            return "-vhdl08"
        elif vhdl_standard == VHDL.STD_1993:
            return "" # default
        else:
            assert False

    def compile_vhdl_file_command(self, source_file):
        """
        Returns command to compile a VHDL file
        """
        cmd = join(self._prefix, 'vhdlan')
        args = []
        args += ['-kdb']
        args += ['-sparse_mem 20']
        args += ['%s' % self._vhdl_std_opt(source_file.get_vhdl_standard())]
        args += ['-work %s' % source_file.library.name]
        args += ['-l %s/vcs_compile_vhdl_file_%s.log' % (self._output_path, source_file.library.name)]
        if not self._log_level == "debug":
            args += ['-q']
            args += ['-nc']
        else:
            args += ['-verbose']
        args += source_file.compile_options.get('vhdl_flags', [])
        args += ['%s' % source_file.name]
        argsfile = "%s/vcs_compile_vhdl_file_%s.args" % (self._output_path, source_file.library.name)
        write_file(argsfile, "\n".join(args))
        # return [cmd, '-full64', '-f', argsfile]
        return [cmd, '-full64', *args]

    def compile_verilog_file_command(self, source_file):
        """
        Returns commands to compile a Verilog file
        """
        cmd = join(self._prefix, 'vlogan')
        args = []
        args += ['-kdb']
        args += ['-sverilog'] # SystemVerilog
        args += ['+v2k'] # Verilog 2001
        args += ['-work %s' % source_file.library.name]
        args += source_file.compile_options.get('vlogan_flags', [])
        args += ['-l %s/vcs_compile_verilog_file_%s.log' % (self._output_path, source_file.library.name)]
        if not self._log_level == "debug":
            args += ['-q']
            args += ['-nc']
        else:
            args += ['-V']
            args += ['-notice']
            args += ['+libverbose']
        for include_dir in source_file.include_dirs:
            args += ['+incdir+%s' % include_dir]
        for key, value in source_file.defines.items():
            args += ['+define+%s=%s' % (key, value.replace('"','\\"'))]
        args += ['+incdir+%s' % os.path.dirname(source_file.name)]
        args += ['%s' % source_file.name]
        argsfile = "%s/vcs_compile_verilog_file_%s.args" % (self._output_path, source_file.library.name)

        write_file(argsfile, "\n".join(args))
        # return [cmd, '-full64', '-f', argsfile]
        return [cmd, '-full64', *args]

    def create_library(self, library_name, library_path, mapped_libraries=None):
        """
        Create and map a library_name to library_path
        """
        mapped_libraries = mapped_libraries if mapped_libraries is not None else {}

        if not file_exists(abspath(library_path)):
            os.makedirs(abspath(library_path))
        if not file_exists(abspath(library_path+"/64/")):
            os.makedirs(abspath(library_path+"/64/"))

        if library_name in mapped_libraries and mapped_libraries[library_name] == library_path:
            return

        vcs = SetupFile.parse(self._vcssetup)
        vcs[library_name] = library_path
        vcs.write(self._vcssetup)

        # _remove_file(self._binaries_path)

    def _get_mapped_libraries(self):
        """
        Get mapped libraries from synopsys_sim.setup file
        """
        vcs = SetupFile.parse(self._vcssetup)
        return vcs

    def elaborate(self, output_path, test_suite_name, file_name, target_file, hierfile):
        """
        Elaborates with entity as top level using generics
        """
        file_dirname = os.path.dirname(file_name)
        
        if not file_exists(output_path):
            os.makedirs(output_path)

        cmd = join(self._prefix, 'vcs')
        shutil.copy(self._vcssetup, output_path)
        vcsargs = []
        vcsargs += [test_suite_name]
        
        vcsargs += ['-o', '/'.join([output_path, 'simv'])]
        vcsargs += ['-licqueue']
        if not self._log_level == "debug":
            vcsargs += ['-q']
            vcsargs += ['-nc']
        else:
            vcsargs += ['-V']
            vcsargs += ['-notice']
        vcsargs += ['-l', f'{output_path}/vcs.log']
        generics = self._generic_args(file_dirname, test_suite_name, 'runner_cfg')
        genericsfile = f"{output_path}/vcs.generics"
        write_file(genericsfile, "\n".join(generics))
        # vcsargs += ['-lca', '-gfile', '%s' % genericsfile]
        vcsargs += target_file.compile_options.get('vcs.vcs_flags', [])

        
        write_file(f'{output_path}/vcs.args', "\n".join(vcsargs))
        return run_command([cmd, '-full64', *vcsargs], cwd=output_path)

    def simulate(  # pylint: disable=too-many-locals
        self, output_path, test_suite_name, config, elaborate_only=False
    ):
        """
        Simulates with entity as top level using generics
        """

        launch_gui = self._gui is not False and not elaborate_only
        
        coverage_file = join(output_path, "simv.vdb")
        self._coverage_files.add(coverage_file)

        elab_path = '%s/%s.%s' % (self._binaries_path, config.library_name, config.entity_name)
        cmd = [join(self._prefix, 'simv')]
        simvargs = config.sim_options.get("vcs.simv_flags", [])

        if config.sim_options.get("enable_coverage", False):
            simvargs += ["-cm_name", test_suite_name]

        macro_file_path = f"{output_path}/simv.tcl"
        self._create_ucli_macro(macro_file_path, launch_gui)
        if launch_gui:
            cmd += ['-gui']
        else:
            test_case_name = test_suite_name.split(".")[-1]
            simvargs += [f"+{test_case_name}"]
            simvargs += [f"+enabled_test_cases={test_case_name}"]
            simvargs += [f"+output_path={output_path}"]

        simvargsfile = f"{output_path}/simv.args"
        write_file(simvargsfile, '\n'.join(simvargs))
        if not elaborate_only:
            # if not run_command([cmd, "-f", simvargsfile], cwd=output_path):
            if not run_command([cmd, *simvargs], cwd=output_path):
                return False
        return True

    def _create_ucli_macro(self, output_path, launch_gui):
        cmd = []
        if not launch_gui:
            cmd += ["set fid [dump -file vcdplus.vpd -type VPD]"]
            cmd += ["dump -fid $fid -depth 0"]
        cmd += ["run"]
        cmd += ["quit"]

        write_file(output_path, "\n".join(cmd))

    @staticmethod
    def _replace_generic_args(value):
        re_test_cases = re.sub('enabled_test_cases\s:\s.*,output\spath\s:', 'enabled_test_cases : __all__,output path :', value)
        return re.sub('output\spath\s:\s.*,tb\spath\s:', 'output path : ./,tb path :', re_test_cases)

    @staticmethod
    def _generic_args(tb_path, entity_name, generics_name):
        """
        Create VCS arguments for generics and parameters
        """
        _value = "active python runner : true,enabled_test_cases : __all__,output path : ./,tb path : %s,use_color : true" % tb_path
        value = VCSInterface._replace_generic_args(_value)
        # args = []
        # for name, value in generics.items():
        if _value_needs_quoting(value):
            args += ['''assign "%s" /%s/%s\n''' % (value, entity_name, generics_name)]
        else:
            args += ['''assign %s /%s/%s\n''' % (value, entity_name, generics_name)]
        return args

def _value_needs_quoting(value):
    if sys.version_info.major == 2:
        if isinstance(value, str) or isinstance(value, bool) or isinstance(value, unicode):
            return True
        else:
            return False
    else:
        if isinstance(value, str) or isinstance(value, bool):
            return True
        else:
            return False

