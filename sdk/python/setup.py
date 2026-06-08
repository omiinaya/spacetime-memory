from setuptools import find_packages, setup

setup(
    name="spacetime-memory",
    version="0.5.0",
    description="SpacetimeDB-powered memory infrastructure for AI agents",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    url="https://github.com/omiinaya/spacetime-memory",
    author="spacetime-memory contributors",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "httpx>=0.27",
    ],
    extras_require={
        "dev": [
            "pytest>=7",
            "pytest-mock>=3",
            "click>=8",
            "feedparser>=6",
        ],
        "langchain": [
            "langchain-core>=0.3",
            "langgraph>=0.2",
        ],
        "all": [
            "langchain-core>=0.3",
            "langgraph>=0.2",
            "feedparser>=6",
        ],
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
