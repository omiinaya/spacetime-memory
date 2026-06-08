from setuptools import setup

setup(
    name="stmem-adapter-mem0",
    version="0.1.0",
    description="Mem0-compatible adapter for Spacetime-Memory",
    py_modules=["stmem_adapter_mem0"],
    python_requires=">=3.10",
    install_requires=[
        "spacetime-memory @ file://$PWD/../../python",
    ],
)
