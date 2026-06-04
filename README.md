This is a AI workflow Project.
the biggest part of this is you can use any module to build any workflow to benefit your daily life .


# Setup Project :   Current Python Version ：Python3.14
pip install -e .
build_and_run.bat

- Production Mode （FastAPI ）

  - Browser： http://127.0.0.1:8766/
- Developer Mode

  - package exe（no config）：
  ```
  cd c:\Project\AITools
  pyinstaller --noconfirm --onefile --name AITools 
  --add-data="webui\dist:webui\dist" --collect-submodules src 
  --collect-submodules fastapi --collect-submodules uvicorn 
  src\fast_api.py
  ```
