"""
Tests ensuring the init command behaves as intented
"""

import os
from itertools import combinations
import tests
from e4s_cl.util import which
from e4s_cl.model.profile import Profile
from e4s_cl.cf.libraries import resolve
from e4s_cl.cf.assets import add_builtin_profile, remove_builtin_profile
from e4s_cl.cli.commands.init import COMMAND, _compile_sample

TEST_SYSTEM = '__test_system'

MPICC = os.environ.get('__E4SCL_MPI_COMPILER', 'mpicc')


class InitTest(tests.TestCase):
    """
    Partial class definition: more tests are defined below
    """

    def setUp(self):
        add_builtin_profile(TEST_SYSTEM, {'name': TEST_SYSTEM})

    def tearDown(self):
        remove_builtin_profile(TEST_SYSTEM)
        Profile.controller().unselect()
        self.resetStorage()

    @tests.skipUnless(which(MPICC), "No MPI compiler found")
    def test_compile_mpicc(self):
        self.assertIsNotNone(_compile_sample(which(MPICC)))

    @tests.skipUnless(which('gcc'), "No GNU compiler found")
    def test_compile_bad_compiler(self):
        self.assertIsNone(_compile_sample(which('gcc')))

    def test_system(self):
        self.assertCommandReturnValue(0, COMMAND, f"--system {TEST_SYSTEM}")
        self.assertEqual(Profile.controller().selected().get('name'),
                         TEST_SYSTEM)

    def test_system_overwrite(self):
        self.assertCommandReturnValue(0, COMMAND, f"--system {TEST_SYSTEM}")
        self.assertEqual(Profile.controller().selected().get('name'),
                         TEST_SYSTEM)
        self.assertEqual(Profile.controller().count(), 1)
        self.assertCommandReturnValue(0, COMMAND, f"--system {TEST_SYSTEM}")
        self.assertEqual(Profile.controller().selected().get('name'),
                         TEST_SYSTEM)
        self.assertEqual(Profile.controller().count(), 1)

    @tests.skipUnless(which(MPICC), "No MPI compiler found")
    def test_wi4mpi(self):
        self.assertCommandReturnValue(0, COMMAND,
                                      "--wi4mpi /path/to/installation")
        profile = Profile.controller().selected()

        self.assertTrue(profile)
        self.assertEqual(profile.get('wi4mpi'), '/path/to/installation')

    @tests.skipUnless(which(MPICC), "No MPI compiler found")
    def test_wi4mpi_overwrite(self):
        self.assertCommandReturnValue(0, COMMAND,
                                      "--wi4mpi /path/to/installation")
        self.assertEqual(Profile.controller().count(), 1)
        self.assertCommandReturnValue(0, COMMAND,
                                      "--wi4mpi /path/to/installation")
        self.assertEqual(Profile.controller().count(), 1)

    def test_rename_system(self):
        self.assertCommandReturnValue(
            0, COMMAND, f"--profile init_test_profile --system {TEST_SYSTEM}")
        self.assertEqual(Profile.controller().selected().get('name'),
                         'init_test_profile')

    @tests.skipUnless(which(MPICC), "No MPI compiler found")
    def test_rename_wi4mpi(self):
        self.assertCommandReturnValue(
            0, COMMAND,
            "--profile init_test_profile --wi4mpi /path/to/installation")
        profile = Profile.controller().selected()

        self.assertTrue(profile)
        self.assertEqual(profile.get('name'), 'init_test_profile')
        self.assertEqual(profile.get('wi4mpi'), '/path/to/installation')


groups = [
    [('--system', TEST_SYSTEM)],
    [
        ('--mpi', '/path/to/installation'),
        ('--launcher', '/path/to/binary'),
        ('--launcher_args', "'-np 8192'"),
    ],
]


def wrapper(option1, value1, option2, value2):
    """
    Generate tests from a simple pattern to ensure all fields are correctly added
    """

    def generated_test(self):
        self.assertNotCommandReturnValue(0, COMMAND,
                                         [option1, value1, option2, value2])

    generated_test.__name__ = f"test_{option1.strip('-')}_{option2.strip('-')}"

    return generated_test


for conflicting_left, conflicting_right in combinations(groups, 2):
    for argument1 in conflicting_left:
        for argument2 in conflicting_right:
            test = wrapper(*argument1, *argument2)
            setattr(InitTest, test.__name__, test)
