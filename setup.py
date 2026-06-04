from setuptools import setup, find_packages

setup(
    name="aitools",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.27.0",
        "python-multipart>=0.0.9",
        "pyautogui>=0.9.54",
        "Pillow>=10.0.0",
    ],
)
