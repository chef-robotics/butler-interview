#!/usr/bin/env python3
import os

import setuptools

package_root = os.path.abspath(os.path.dirname(__file__))

version = {}
with open(os.path.join(package_root, "chefrobotics/butler/version.py")) as fp:
    exec(fp.read(), version)
version = version["__version__"]

packages = [
    package
    for package in setuptools.PEP420PackageFinder.find()
    if package.startswith("chefrobotics")
]
print("PACKAGES:", packages)

setuptools.setup(
    name="chefrobotics-butler",
    version=version,
    author="Chef Robotics, Inc",
    author_email="software@chefrobotics.ai",
    license="Proprietary",
    install_requires=(
        "alembic == 1.12.1",
        "fastapi == 0.95.0",
        "httpx == 0.24.1",
        "requests >= 2.18.0,<3",
        "pexpect == 4.9.0",
        "SQLAlchemy == 2.0.21",
        "uvicorn[standard] == 0.22.0",
    ),
    platforms="Posix",
    python_requires=">=3.7",
    packages=packages,
    namespace_packages=["chefrobotics"],
    entry_points="""
        [console_scripts]
        butler-server=chefrobotics.butler.services.server:main
        butler-dispatcher=chefrobotics.butler.services.dispatcher:main
        butler-db-migrate=chefrobotics.butler.services.setup_and_check_db:main
    """,
)
