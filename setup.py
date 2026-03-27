from setuptools import find_packages, setup


setup(
    name="email-ops-mcp",
    version="0.2.0",
    description="EMail-Ops-MCP: structured stdio MCP server for schema-v2 mailbox setup, migration, inbox search, attachment download, and sending email.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["mcp>=1.0.0"],
    extras_require={"secure-storage": ["keyring>=24"]},
    entry_points={"console_scripts": ["email-ops-mcp=email_ops.__main__:main"]},
)
