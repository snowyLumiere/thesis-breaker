"""Backward-compatible setup shim.

On setuptools >= 61.0, all metadata is read from PEP 621 [project] in pyproject.toml.
On legacy setuptools (< 61.0, such as macOS system Python 3.9), fallback metadata
ensures offline editable installs (`pip install -e . --no-build-isolation`) still work.
"""

import setuptools

if int(setuptools.__version__.split(".", 1)[0]) < 61:
    setuptools.setup(
        name="thesis-breaker",
        version="0.1.0",
        description=(
            "Zero-API-cost local position postmortem, SOTP/FCFE valuation re-pricing, "
            "and thesis-drift discipline officer for US/HK equity investors."
        ),
        author="SnowyLumiere",
        license="MIT",
        python_requires=">=3.9",
        package_dir={"": "src"},
        packages=setuptools.find_packages(where="src"),
        entry_points={
            "console_scripts": [
                "thesis-breaker = thesis_breaker.cli:main",
            ]
        },
    )
else:
    setuptools.setup()
