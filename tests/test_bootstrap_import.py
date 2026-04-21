import importlib
import os
import sys


def test_import_bootstrap_does_not_set_env_var_side_effect():
    absent_var = "BOOTSTRAP_IMPORT_SIDE_EFFECT_TEST_VAR"
    assert absent_var not in os.environ

    sys.modules.pop("bootstrap", None)
    importlib.import_module("bootstrap")

    assert absent_var not in os.environ
