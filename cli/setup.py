from setuptools import setup

setup(
    name="stmem",
    version="0.1.0",
    py_modules=["stmem"],
    install_requires=[
        "click>=8.1",
        "httpx>=0.27",
        "rich>=13.0",
    ],
    entry_points={
        "console_scripts": [
            "stmem=stmem:cli",
        ],
    },
    python_requires=">=3.10",
)
