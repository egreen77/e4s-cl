from os import getenv, getcwd
from tempfile import NamedTemporaryFile
from unittest import skipIf
from pathlib import Path
import tests
from e4s_cl.util import which
from e4s_cl.cf.containers import Container, BackendUnsupported, FileOptions
from e4s_cl.cf.containers.shifter import _parse_config, organize_config

SAMPLE_CONFIG = """#system (required)
#
# Name of your system, e.g., edison or cori. This name must match a configured 
# system in the imagegw. This is primarily used by shifterimg to self-identify 
# which system it is representing.
#
system=perlmutter
siteFs=/path1:/path1;\\
    /path2:/path2;
siteEnv=SHIFTER_RUNTIME=1
module_test_siteFs = test
this line is an issue and should be dropped
"""

EXPECTED_CONFIG = dict(system='perlmutter',
                       siteFs='/path1:/path1;/path2:/path2;',
                       siteEnv='SHIFTER_RUNTIME=1',
                       module_test_siteFs='test')


class ContainerTestShifter(tests.TestCase):

    def shifter_check():
        return (not which('shifter') and (not Path('shifter').exists()))

    def test_parse_config(self):
        with NamedTemporaryFile('w', delete=False) as config:
            config.write(SAMPLE_CONFIG)
            config_file = config.name

        directives = _parse_config(config_file)

        self.assertSetEqual(set(EXPECTED_CONFIG.keys()),
                            set(directives.keys()))
        self.assertSetEqual(set(EXPECTED_CONFIG.values()),
                            set(directives.values()))

        organized = organize_config(directives)

        old_var = directives.get('module_test_siteFs')
        module_dir = directives.get('module', {})
        test_dir = module_dir.get('test', {})
        self.assertIsNone(old_var)
        self.assertTrue(module_dir)
        self.assertTrue(test_dir)
        self.assertEqual(test_dir.get('siteFs'), 'test')

    def test_create(self):
        container = Container(name='shifter', image='test')
        self.assertFalse(type(container) == Container)
        self.assertTrue(isinstance(container, Container))

    @skipIf(shifter_check(), "Shifter absent from system")
    def test_run_backend(self):
        container = Container(name='shifter')
        command = ['']
        container_cmd = container._prepare(command)
        self.assertIn('shifter', ' '.join(map(str, container_cmd)))

    def test_run_image(self):
        container = Container(name='shifter', image='imagenametest')
        command = ['']
        container_cmd = container._prepare(command)
        self.assertIn('imagenametest', ' '.join(map(str, container_cmd)))

    def test_run_mpirun(self):
        container = Container(name='shifter', image='dummyimagename')
        command = ['mpirun -n 2 ls']
        container_cmd = container._prepare(command)
        self.assertIn(command[0], ' '.join(map(str, container_cmd)))

    def test_bind_file(self):
        container = Container(name='shifter')

        target = Path('/tmp')
        dest = Path('/tmp')
        option = FileOptions.READ_WRITE

        container.bind_file(target)
        self.assertIn((target, target, FileOptions.READ_ONLY),
                      list(container.bound))

        container.bind_file(target, dest=dest)
        self.assertIn((target, dest, FileOptions.READ_ONLY),
                      list(container.bound))

        container.bind_file(target, dest=dest, option=option)
        self.assertIn((target, dest, FileOptions.READ_WRITE),
                      list(container.bound))

    def test_bind_relative(self):
        container = Container(name='shifter')

        target = Path('/tmp/../proc/meminfo')

        ref = Path('/tmp')
        file = Path('/proc/meminfo')

        container.bind_file(target)
        files = set(map(lambda x: x[0], container.bound))

        self.assertSetEqual({ref, file}, files)
