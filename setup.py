from setuptools import setup, find_packages

setup(
    name="agentpark",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.27.0",
        "python-multipart>=0.0.9",
        "pyautogui>=0.9.54",
        "Pillow>=11.1.0",
        "pillow-heif>=0.18.0",
        "cryptography>=42.0.0",
        "mcp>=1.28.0",
        "prompt_toolkit>=3.0.52",
        "PyYAML>=6.0",
        "protobuf>=7.35.0",
    ],
)
