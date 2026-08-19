import importlib
import pathlib
import unittest

from app.settings import validate_runtime_config


class ImportSmokeTests(unittest.TestCase):
    def test_runtime_config_is_valid(self):
        validate_runtime_config()

    def test_every_application_module_imports(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        module_paths = [root / "main.py", *sorted((root / "app").rglob("*.py"))]
        imported = []
        for path in module_paths:
            relative = path.relative_to(root).with_suffix("")
            module_name = ".".join(relative.parts)
            importlib.import_module(module_name)
            imported.append(module_name)

        self.assertGreater(len(imported), 25)


if __name__ == "__main__":
    unittest.main()
