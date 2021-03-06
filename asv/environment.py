# -*- coding: utf-8 -*-
# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""
Manages an environment -- a combination of a version of Python and set
of dependencies.
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import inspect
import os
import shutil

import six

from .console import log
from . import util


def get_environments(conf):
    """
    Iterator returning `Environment` objects for all of the
    permutations of the given versions of Python and a matrix of
    requirements.

    Parameters
    ----------
    env_dir : str
        Root path in which to cache environments on disk.

    pythons : sequence of str
        A list of versions of Python

    matrix : dict of package to sequence of versions
    """
    def iter_matrix(matrix):
        if len(matrix) == 0:
            yield dict()
            return

        # TODO: Deal with matrix exclusions
        matrix = dict(matrix)
        key = next(six.iterkeys(matrix))
        entry = matrix[key]
        del matrix[key]

        for result in iter_matrix(matrix):
            if len(entry):
                for value in entry:
                    d = dict(result)
                    d[key] = value
                    yield d
            else:
                d = dict(result)
                d[key] = None
                yield d

    for python in conf.pythons:
        for configuration in iter_matrix(conf.matrix):
            yield Environment(conf.env_dir, python, configuration)


class Environment(object):
    """
    Manage a single environment -- a combination of a particular
    version of Python and a set of dependencies for the benchmarked
    project.

    Environments are created in the
    """
    def __init__(self, env_dir, python, requirements):
        """
        Parameters
        ----------
        env_dir : str
            Root path in which to cache environments on disk.

        python : str
            Version of Python.  Must be of the form "MAJOR.MINOR".

        requirements : dict
            Dictionary mapping a PyPI package name to a version
            identifier string.
        """
        executables = util.which("python{0}".format(python))
        if len(executables) == 0:
            raise RuntimeError(
                "No executable found for version {0}".format(python))
        self._executable = executables
        self._env_dir = env_dir
        self._python = python
        self._requirements = requirements
        self._path = os.path.join(
            self._env_dir, self.name)

        try:
            import virtualenv
        except ImportError:
            raise RuntimeError("virtualenv must be installed to run asv")

        # Can't use `virtualenv.__file__` here, because that will refer to a
        # .pyc file which can't be used on another version of Python
        self._virtualenv_path = os.path.abspath(
            inspect.getsourcefile(virtualenv))

        self._is_setup = False
        self._requirements_installed = False

    @property
    def name(self):
        """
        Get a name to uniquely identify this environment.
        """
        name = ["py{0}".format(self._python)]
        reqs = list(six.iteritems(self._requirements))
        reqs.sort()
        for key, val in reqs:
            if val is not None:
                name.append(''.join([key, val]))
            else:
                name.append(key)
        return '-'.join(name)

    @property
    def requirements(self):
        return self._requirements

    @property
    def python(self):
        return self._python

    def setup(self):
        """
        Setup the environment on disk.  If it doesn't exist, it is
        created using virtualenv.  Then, all of the requirements are
        installed into it using `pip install`.
        """
        if self._is_setup:
            return

        if not os.path.exists(self._env_dir):
            os.makedirs(self._env_dir)

        try:
            log.info("Creating virtualenv for {0}".format(self.name))
            if not os.path.exists(self._path):
                util.check_call([
                    self._executable,
                    self._virtualenv_path,
                    '--no-site-packages',
                    self._path])
        except:
            log.error("Failure creating virtualenv for {0}".format(self.name))
            if os.path.exists(self._path):
                shutil.rmtree(self._path)
            raise

        self._is_setup = True

    def install_requirements(self):
        if self._requirements_installed:
            return

        self.setup()

        self.upgrade('setuptools')

        for key, val in six.iteritems(self._requirements):
            if val is not None:
                self.upgrade("{0}=={1}".format(key, val))
            else:
                self.upgrade(key)

        self._requirements_installed = True

    def _run_executable(self, executable, args, **kwargs):
        return util.check_output([
            os.path.join(self._path, 'bin', executable)] + args, **kwargs)

    def install(self, package, editable=False):
        """
        Install a package into the environment using `pip install`.
        """
        log.info("Installing {0} into {1}".format(package, self.name))
        args = ['install']
        if editable:
            args.append('-e')
        args.append(package)
        self._run_executable('pip', args)

    def upgrade(self, package):
        """
        Upgrade a package into the environment using `pip install --upgrade`.
        """
        log.info("Upgrading {0} in {1}".format(package, self.name))
        self._run_executable('pip', ['install', '--upgrade', package])

    def uninstall(self, package):
        """
        Uninstall a package into the environment using `pip uninstall`.
        """
        log.info("Uninstalling {0} from {1}".format(package, self.name))
        self._run_executable('pip', ['uninstall', '-y', package], error=False)

    def run(self, args, **kwargs):
        """
        Start up the environment's python executable with the given
        args.
        """
        log.debug("Running '{0}' in {1}".format(' '.join(args), self.name))
        self.install_requirements()
        return self._run_executable('python', args, **kwargs)

    def install_project(self, conf):
        """
        Install a working copy of the benchmarked project into the
        environment.  Uninstalls any installed copy of the project
        first.
        """
        self.install_requirements()
        self.uninstall(conf.project)
        self.install(os.path.abspath(conf.project), editable=True)
