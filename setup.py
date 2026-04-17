from setuptools import find_packages, setup


setup(
    name="ci-sponsor-guide-updater",
    version="0.1.0",
    packages=find_packages(include=["app", "app.*", "src", "src.*"]),
    python_requires=">=3.11",
)
